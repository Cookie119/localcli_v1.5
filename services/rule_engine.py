from sqlalchemy import text
from models.base import db_session
import json
import traceback

class RuleEngine:
    def __init__(self, regulation_id):
        self.regulation_id = regulation_id
        self.rules = self._load_rules()
        # Simple cache for regulation-level metadata if needed later
        self._regulation_meta = None
    
    def _load_rules(self):
        """Load all active rules for the regulation"""
        try:
            query = text("""
                SELECT r.*, 
                       json_agg(json_build_object(
                           'name', rp.parameter_name,
                           'value', rp.parameter_value,
                           'unit', rp.unit
                       )) as parameters
                FROM rules r
                LEFT JOIN rule_parameters rp ON r.id = rp.rule_id
                WHERE r.regulation_id = :reg_id AND r.is_active = true
                GROUP BY r.id
            """)
            result = db_session.execute(query, {'reg_id': self.regulation_id})
            rules = []
            for row in result:
                # Convert row to dict safely
                rule_dict = {}
                for key in row._mapping.keys():
                    rule_dict[key] = row._mapping[key]
                rules.append(rule_dict)
            
            print(f"Loaded {len(rules)} rules for regulation {self.regulation_id}")
            return rules
        except Exception as e:
            print(f"Error loading rules: {e}")
            traceback.print_exc()
            return []

    def _resolve_var(self, context, path, default=None):
        """
        Resolve a variable from the context for JSON-expression rules.
        Supports simple dot-separated paths like 'plot.area' if needed later;
        currently we treat everything as top-level keys.
        """
        if not path:
            return default
        key = str(path)
        return context.get(key, default)

    def _eval_expression(self, expr, context):
        """
        Minimal JSON-logic style evaluator for rule expressions (FR-20).
        Supports:
        - {"var": "name"}
        - {"<": [a, b]}, {"<=": [...]}, {">": [...]}, {">=": [...]}, {"==": [...]}, {"!=": [...]}
        - {"and": [cond1, cond2, ...]}, {"or": [cond1, cond2, ...]}
        - {"+": [a, b, ...]}, {"-": [a, b]}, {"*": [a, b, ...]}, {"/": [a, b]}
        """
        # Primitive values pass through
        if not isinstance(expr, dict):
            return expr

        if "var" in expr:
            return self._resolve_var(context, expr["var"])

        if len(expr) != 1:
            # Ambiguous; treat as truthy
            return True

        op, args = next(iter(expr.items()))
        if not isinstance(args, list):
            args = [args]

        # Resolve all arguments
        values = [self._eval_expression(a, context) for a in args]

        # Comparison ops
        if op in ("<", "<=", ">", ">=", "==", "!=") and len(values) >= 2:
            a, b = values[0], values[1]
            try:
                if op == "<":
                    return a < b
                if op == "<=":
                    return a <= b
                if op == ">":
                    return a > b
                if op == ">=":
                    return a >= b
                if op == "==":
                    return a == b
                if op == "!=":
                    return a != b
            except Exception:
                return False

        # Logical ops
        if op == "and":
            return all(bool(v) for v in values)
        if op == "or":
            return any(bool(v) for v in values)

        # Arithmetic ops
        try:
            if op == "+":
                return sum(float(v or 0) for v in values)
            if op == "-":
                if len(values) == 1:
                    return -float(values[0] or 0)
                return float(values[0] or 0) - float(values[1] or 0)
            if op == "*":
                res = 1.0
                for v in values:
                    res *= float(v or 0)
                return res
            if op == "/":
                if len(values) < 2:
                    return None
                numerator = float(values[0] or 0)
                denominator = float(values[1] or 0) or 1e-9
                return numerator / denominator
        except Exception:
            return None

        # Fallback: treat unknown ops as truthy
        return True
    
    def evaluate_rule(self, rule, context):
        """Evaluate a single rule against the design context"""
        try:
            # Get expression logic safely
            expression = rule.get('expression_logic', {})
            if isinstance(expression, str):
                try:
                    expression = json.loads(expression)
                except:
                    expression = {}
            rule_code = rule.get('rule_code', '')
            rule_type = rule.get('rule_type')  # e.g. hard / soft / advisory
            category = rule.get('category')    # e.g. setback / FAR / fire / height

            # State-aware helpers
            state_code = context.get('state') or context.get('state_code')
            total_floors = context.get('total_floors')
            floor_height = context.get('floor_height') or 3.0
            building_height_ctx = context.get('building_height')
            if building_height_ctx is None and total_floors:
                try:
                    building_height_ctx = float(total_floors) * float(floor_height)
                except Exception:
                    building_height_ctx = None

            # Simple evaluation for now, extended for priority FRs
            if 'FAR' in rule_code:
                # FAR calculation
                plot_area = context.get('plot_area', 500)
                far_factor = expression.get('far_factor', 2.0) if isinstance(expression, dict) else 2.0
                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': True,
                    'actual': plot_area * far_factor,
                        'expected': far_factor
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            elif 'SETBACK' in rule_code:
                # Setback rules (state-aware, road-width based)
                road_width = context.get('road_width', 12) or 12

                # Maharashtra (UDCPR-style) dynamic front setback
                # FR-19: 3.0m for road ≤ 6.0m, 4.5m for road > 9.0m
                if state_code == 'MH':
                    if road_width <= 6:
                        required_setback = 3.0
                    elif road_width > 9:
                        required_setback = 4.5
                    else:
                        # Mid-band – keep conservative 3.0m
                        required_setback = 3.0
                # Goa basic front setback (FR-18)
                elif state_code == 'GA':
                    # Front setback 3.0m – side/rear handled by separate rules
                    required_setback = 3.0
                else:
                    # Default generic rule – keep previous behaviour
                    required_setback = 3 if road_width > 10 else 1.5

                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': True,
                    'actual': required_setback,
                    'expected': required_setback
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Goa minimum plot area (FR-18)
            elif 'GA_MIN_PLOT_AREA' in rule_code:
                plot_area = context.get('plot_area', 0) or 0
                min_area = 200.0
                if isinstance(expression, dict):
                    min_area = float(expression.get('min_area', min_area))
                passed = plot_area >= min_area
                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': float(plot_area),
                    'expected': float(min_area)
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Goa max height (simplified G+1, 9.0m) – FR-18
            elif 'GA_MAX_HEIGHT' in rule_code:
                building_height = building_height_ctx or context.get('building_height', 0) or 0
                max_height = 9.0
                if isinstance(expression, dict):
                    max_height = float(expression.get('max_height', max_height))
                passed = building_height <= max_height
                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': float(building_height),
                    'expected': float(max_height)
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Goa max FSI (default 1.5, zone-dependent later)
            elif 'GA_MAX_FSI' in rule_code:
                used_fsi = context.get('used_fsi', 0) or 0
                max_fsi = 1.5
                if isinstance(expression, dict):
                    max_fsi = float(expression.get('max_fsi', max_fsi))
                passed = used_fsi <= max_fsi
                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': float(used_fsi),
                    'expected': float(max_fsi)
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Height-based fire access rule (e.g. MH FIRE_ACCESS)
            elif 'FIRE_ACCESS' in rule_code:
                min_height = 24.0
                min_road_width = 6.0
                if isinstance(expression, dict):
                    min_height = float(expression.get('min_height', min_height))
                    min_road_width = float(expression.get('min_road_width', min_road_width))

                building_height = building_height_ctx or context.get('building_height', 0) or 0
                road_width = context.get('road_width', 0) or 0
                has_fire_access_road = bool(context.get('has_fire_access_road', False))
                fire_access_width = context.get('fire_access_width', road_width) or road_width

                # Only applicable if building exceeds threshold
                if building_height <= min_height:
                    passed = True
                else:
                    passed = has_fire_access_road and fire_access_width >= min_road_width

                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': {
                        'building_height': float(building_height),
                        'fire_access_width': float(fire_access_width),
                    },
                    'expected': {
                        'min_height': float(min_height),
                        'min_road_width': float(min_road_width),
                    },
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Refuge area mandatory above specified height
            elif 'REFUGE_AREA' in rule_code:
                min_height = 30.0
                if isinstance(expression, dict):
                    min_height = float(expression.get('min_height', min_height))

                building_height = building_height_ctx or context.get('building_height', 0) or 0
                has_refuge = bool(context.get('has_refuge_area', False))

                if building_height <= min_height:
                    passed = True
                else:
                    passed = has_refuge

                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': {
                        'building_height': float(building_height),
                        'has_refuge_area': has_refuge,
                    },
                    'expected': {
                        'min_height': float(min_height),
                        'refuge_required': True,
                    },
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            # Premium FSI logic – allow higher FSI if premium purchased
            elif 'PREMIUM_FSI' in rule_code:
                used_fsi = context.get('used_fsi', 0) or 0
                base_fsi = 1.0
                max_premium_fsi = 0.5
                has_premium = bool(context.get('has_premium_fsi', False))
                if isinstance(expression, dict):
                    base_fsi = float(expression.get('base_fsi', base_fsi))
                    max_premium_fsi = float(expression.get('max_premium_fsi', max_premium_fsi))

                allowed_fsi = base_fsi + (max_premium_fsi if has_premium else 0.0)
                passed = used_fsi <= allowed_fsi

                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': float(used_fsi),
                    'expected': float(allowed_fsi),
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
            else:
                # Generic JSON-expression rule evaluation
                passed = True
                actual = None
                expected = None

                if isinstance(expression, dict) and expression:
                    try:
                        eval_result = self._eval_expression(expression, context)
                        passed = bool(eval_result)
                        actual = eval_result
                    except Exception as e:
                        print(f"Error evaluating generic expression for rule {rule_code}: {e}")
                        passed = False

                base = {
                    'rule_id': rule.get('id'),
                    'rule_code': rule_code,
                    'passed': passed,
                    'actual': actual,
                    'expected': expected
                }
                if rule_type:
                    base['rule_type'] = rule_type
                if category:
                    base['category'] = category
                return base
                
        except Exception as e:
            print(f"Error evaluating rule: {e}")
            return {
                'rule_id': rule.get('id'),
                'rule_code': rule.get('rule_code', 'UNKNOWN'),
                'passed': False,
                'error': str(e)
            }
    
    def evaluate_all(self, design_context):
        """Evaluate all rules against the design"""
        results = []
        for rule in self.rules:
            result = self.evaluate_rule(rule, design_context)
            results.append(result)
            
            # Try to store in database, but don't fail if it doesn't work
            try:
                self._store_result(design_context.get('design_id', 0), rule.get('id'), result)
            except:
                pass  # Silently fail storage
        
        return results

    @staticmethod
    def summarize_results(results):
        """Summarize a list of rule results into an overall compliance status."""
        summary = {
            'hard_failed': 0,
            'soft_failed': 0,
            'advisory_failed': 0,
            'total': len(results or []),
            'overall_status': 'not_evaluated',
        }

        if not results:
            return summary

        for r in results:
            if not isinstance(r, dict):
                continue
            passed = r.get('passed', True)
            rule_type = (r.get('rule_type') or '').lower()
            if passed:
                continue
            if rule_type == 'hard':
                summary['hard_failed'] += 1
            elif rule_type == 'soft':
                summary['soft_failed'] += 1
            elif rule_type == 'advisory':
                summary['advisory_failed'] += 1

        if summary['hard_failed'] > 0:
            summary['overall_status'] = 'non_compliant'
        elif summary['soft_failed'] > 0:
            summary['overall_status'] = 'conditionally_compliant'
        elif summary['advisory_failed'] > 0:
            summary['overall_status'] = 'compliant_with_warnings'
        else:
            summary['overall_status'] = 'compliant'

        return summary
    
    def _store_result(self, design_id, rule_id, result):
   
        try:
            # Extract values with type conversion
            actual_value = result.get('actual')
            expected_value = result.get('expected')
            remarks = result.get('error', '')
            
            # Handle boolean values - convert to 1/0
            if isinstance(actual_value, bool):
                actual_value = 1.0 if actual_value else 0.0
            if isinstance(expected_value, bool):
                expected_value = 1.0 if expected_value else 0.0
            
            # Handle dictionary values - can't store in numeric column
            if isinstance(actual_value, dict):
                # Store dict as JSON string in remarks instead
                remarks += f" | actual: {json.dumps(actual_value)}"
                actual_value = None
            if isinstance(expected_value, dict):
                remarks += f" | expected: {json.dumps(expected_value)}"
                expected_value = None
            
            # Handle None values
            if actual_value is None:
                actual_value = 0.0
            if expected_value is None:
                expected_value = 0.0
                
            # Ensure numeric types
            try:
                actual_value = float(actual_value)
            except (TypeError, ValueError):
                actual_value = 0.0
                
            try:
                expected_value = float(expected_value)
            except (TypeError, ValueError):
                expected_value = 0.0
            
            with db_session.begin_nested():
                query = text("""
                    INSERT INTO compliance_results 
                        (design_id, rule_id, status, actual_value, expected_value, remarks)
                    VALUES 
                        (:design_id, :rule_id, :status, :actual, :expected, :remarks)
                    ON CONFLICT (design_id, rule_id) 
                    DO UPDATE SET 
                        status = EXCLUDED.status,
                        actual_value = EXCLUDED.actual_value,
                        expected_value = EXCLUDED.expected_value,
                        remarks = EXCLUDED.remarks,
                        evaluated_at = now()
                """)
                
                db_session.execute(query, {
                    'design_id': design_id,
                    'rule_id': rule_id,
                    'status': 'pass' if result.get('passed') else 'fail',
                    'actual': actual_value,
                    'expected': expected_value,
                    'remarks': remarks
                })
        except Exception as e:
            print(f"Error storing compliance result: {e}")
            # No rollback needed - savepoint handles it