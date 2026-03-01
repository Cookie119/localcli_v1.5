from flask import Blueprint, request, jsonify
from sqlalchemy import text
from decimal import Decimal

from models.base import db_session
from models.project import Design
from models.cost import RateCard, BOQItem
from models.audit import AuditLog
from services.rule_engine import RuleEngine

bp = Blueprint('cost', __name__, url_prefix='/api/cost')


def _decimal(value, default=0):
    try:
        if value is None:
            return Decimal(str(default))
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


@bp.route('/projects/<int:project_id>/boq/generate', methods=['POST'])
def generate_boq(project_id):
    """
    Generate BOQ from design + rate cards (FR-29/30/31, backend MVP).

    Body params:
    - design_id (optional; if omitted, uses latest design for project)
    - state_code, city, project_type_code (optional filters for rate cards)
    """
    try:
        data = request.json or {}
        design_id = data.get('design_id')

        # Resolve design if not explicitly provided: pick latest by id
        if not design_id:
            row = db_session.execute(
                text(
                    "SELECT id FROM designs "
                    "WHERE project_version_id IN ("
                    "  SELECT id FROM project_versions WHERE project_id = :pid"
                    ") ORDER BY id DESC LIMIT 1"
                ),
                {'pid': project_id},
            ).first()
            if not row:
                return jsonify({'error': 'No design found for project'}), 404
            design_id = row[0]

        design = db_session.query(Design).filter(Design.id == design_id).first()
        if not design:
            return jsonify({'error': 'Design not found'}), 404

        built_up_area = _decimal(design.built_up_area, 0)

        # Basic metrics; later you can add carpet/super built-up, etc.
        metrics = {
            'built_up_area': built_up_area,
            'total_floors': Decimal(design.total_floors or 0),
            'total_units': Decimal(design.total_units or 0),
        }

        # Fetch applicable rate cards
        q = db_session.query(RateCard).filter(RateCard.is_active == True)  # noqa

        if data.get('state_code'):
            q = q.filter(RateCard.state_code == data['state_code'])
        if data.get('city'):
            q = q.filter(RateCard.city == data['city'])
        if data.get('project_type_code'):
            q = q.filter(RateCard.project_type_code == data['project_type_code'])

        rate_cards = q.all()
        if not rate_cards:
            return jsonify({'error': 'No active rate cards found for filters'}), 404

        # Clear existing auto-generated BOQ for this design to avoid duplicates
        db_session.query(BOQItem).filter(
            BOQItem.project_id == project_id,
            BOQItem.design_id == design_id,
            BOQItem.source == 'auto',
        ).delete(synchronize_session=False)

        items = []
        total_amount = Decimal('0')

        for rc in rate_cards:
            source_metric = rc.quantity_source or 'built_up_area'
            base_metric = metrics.get(source_metric, built_up_area)
            multiplier = _decimal(rc.quantity_multiplier, 1)
            quantity = (base_metric * multiplier).quantize(Decimal('0.001'))
            rate = _decimal(rc.base_rate, 0)
            amount = (quantity * rate).quantize(Decimal('0.01'))

            item = BOQItem(
                project_id=project_id,
                design_id=design_id,
                category=rc.category,
                item_code=rc.item_code,
                description=rc.description,
                unit=rc.unit,
                quantity=quantity,
                rate=rate,
                amount=amount,
                source='auto',
            )
            db_session.add(item)
            items.append(item)
            total_amount += amount

        db_session.commit()

        # Audit
        AuditLog.log(
            project_id=project_id,
            design_id=design_id,
            entity_type='boq',
            entity_id=None,
            action='generate',
            after_state={'total_amount': float(total_amount)},
        )

        return jsonify({
            'project_id': project_id,
            'design_id': design_id,
            'total_amount': float(total_amount),
            'items': [
                {
                    'id': i.id,
                    'category': i.category,
                    'item_code': i.item_code,
                    'description': i.description,
                    'unit': i.unit,
                    'quantity': float(i.quantity),
                    'rate': float(i.rate),
                    'amount': float(i.amount),
                    'source': i.source,
                }
                for i in items
            ],
        })
    except Exception as e:
        db_session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/boq-items/<int:item_id>', methods=['PATCH'])
def override_boq_item(item_id):
    """
    Manual override of BOQ item quantity/rate with audit logging (FR-29/30/31 & FR-36).

    Body:
    - quantity (optional)
    - rate (optional)
    - override_reason (required if any change)
    """
    try:
        data = request.json or {}
        item = db_session.query(BOQItem).filter(BOQItem.id == item_id).first()
        if not item:
            return jsonify({'error': 'BOQ item not found'}), 404

        if any(k in data for k in ('quantity', 'rate')) and not data.get('override_reason'):
            return jsonify({'error': 'override_reason is required when overriding quantity or rate'}), 400

        before = {
            'quantity': float(item.quantity),
            'rate': float(item.rate),
            'amount': float(item.amount),
            'override_reason': item.override_reason,
        }

        changed = False
        if 'quantity' in data:
            item.quantity = _decimal(data['quantity'], item.quantity)
            changed = True
        if 'rate' in data:
            item.rate = _decimal(data['rate'], item.rate)
            changed = True

        if changed:
            item.amount = (item.quantity * item.rate).quantize(Decimal('0.01'))
            item.source = 'manual'
            item.override_reason = data.get('override_reason')

        db_session.add(item)
        db_session.commit()

        AuditLog.log(
            project_id=item.project_id,
            design_id=item.design_id,
            entity_type='boq_item',
            entity_id=item.id,
            action='override' if changed else 'noop',
            before_state=before,
            after_state={
                'quantity': float(item.quantity),
                'rate': float(item.rate),
                'amount': float(item.amount),
                'override_reason': item.override_reason,
            },
        )

        return jsonify({
            'id': item.id,
            'project_id': item.project_id,
            'design_id': item.design_id,
            'category': item.category,
            'item_code': item.item_code,
            'description': item.description,
            'unit': item.unit,
            'quantity': float(item.quantity),
            'rate': float(item.rate),
            'amount': float(item.amount),
            'source': item.source,
            'override_reason': item.override_reason,
        })
    except Exception as e:
        db_session.rollback()
        return jsonify({'error': str(e)}), 500

