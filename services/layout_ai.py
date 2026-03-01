# services/layout_ai.py
from groq import Groq
import os
import json
import time
import math
import random
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()


class LayoutAI:
    """
    AI-powered layout generator using proper ZONE-BASED 2D grid placement.

    ZONE ORDER (top = rear external wall → bottom = corridor/entrance):
        Zone 1 (TOP)    : Balcony  — rear external wall, full flat width
        Zone 2          : Living | Kitchen  — side by side, full flat width
        Zone 3          : Bedroom1 | Bathroom1 | Bedroom2 | Bathroom2  — side by side
        Zone 4          : Dining  — full flat width
        Zone 5 (BOTTOM) : Passage  — entrance/corridor side, full flat width
    """

    WALL_THICKNESS = 0.15   # metres (internal partition walls)

    # ── Bathroom width is intentionally capped at 2.0 m ────────────────────
    MAX_ROOM_SIZES = {
        "1BHK": {
            "living": 22, "bedroom": 16, "kitchen": 9,
            "bathroom": 5, "balcony": 5, "passage": 4
        },
        "2BHK": {
            "living": 26, "bedroom1": 18, "bedroom2": 16, "kitchen": 10,
            "bathroom1": 5, "bathroom2": 4,
            "balcony": 6, "passage": 4, "dining": 8
        },
        "3BHK": {
            "living": 30, "bedroom1": 20, "bedroom2": 18, "bedroom3": 16,
            "kitchen": 12, "bathroom1": 5, "bathroom2": 4, "bathroom3": 4,
            "balcony": 7, "passage": 5, "dining": 10
        },
    }

    MIN_ROOM_SIZES = {
        "1BHK": {
            "living": 14, "bedroom": 10, "kitchen": 5,
            "bathroom": 3, "balcony": 3, "passage": 2
        },
        "2BHK": {
            "living": 16, "bedroom1": 11, "bedroom2": 10, "kitchen": 6,
            "bathroom1": 3, "bathroom2": 3,
            "balcony": 3, "passage": 2, "dining": 5
        },
        "3BHK": {
            "living": 18, "bedroom1": 12, "bedroom2": 11, "bedroom3": 10,
            "kitchen": 7, "bathroom1": 3, "bathroom2": 3, "bathroom3": 3,
            "balcony": 4, "passage": 2, "dining": 6
        },
    }

    # Percentages sum to ~0.88 — leaving 12 % for walls & circulation
    ROOM_PERCENTAGES = {
        "1BHK": {
            "living": 0.27, "bedroom": 0.22, "kitchen": 0.12,
            "bathroom": 0.07, "balcony": 0.06, "passage": 0.06
        },
        "2BHK": {
            "living": 0.20, "bedroom1": 0.14, "bedroom2": 0.12, "kitchen": 0.09,
            "bathroom1": 0.05, "bathroom2": 0.04,
            "balcony": 0.06, "passage": 0.04, "dining": 0.06
        },
        "3BHK": {
            "living": 0.17, "bedroom1": 0.12, "bedroom2": 0.10, "bedroom3": 0.09,
            "kitchen": 0.08, "bathroom1": 0.05, "bathroom2": 0.04, "bathroom3": 0.03,
            "balcony": 0.05, "passage": 0.03, "dining": 0.05
        },
    }

    # ── Zone definitions ──────────────────────────────────────────────────
    # Order is LOW Y → HIGH Y  (CAD Y-axis increases upward)
    # flat_y = bottom = corridor/entrance side  → passage goes first
    # flat_y + flat_length = top = rear wall    → balcony goes last
    ZONES = {
        "1BHK": [
            ("passage_zone",  ["passage"]),                    # lowest Y — entrance side
            ("bedroom_zone",  ["bedroom", "bathroom"]),
            ("living_zone",   ["living", "kitchen"]),          # side by side
            ("balcony_zone",  ["balcony"]),                    # highest Y — rear wall
        ],
        "2BHK": [
            ("passage_zone",  ["passage"]),                    # lowest Y — entrance side
            ("bedroom_zone",  ["bedroom1", "bathroom1", "bedroom2", "bathroom2"]),
            ("living_zone",   ["living", "dining", "kitchen"]),# dining between living & kitchen
            ("balcony_zone",  ["balcony"]),                    # highest Y — rear wall
        ],
        "3BHK": [
            ("passage_zone",  ["passage"]),                    # lowest Y — entrance side
            ("bedroom_zone",  ["bedroom1", "bathroom1", "bedroom2", "bathroom2",
                               "bedroom3", "bathroom3"]),
            ("living_zone",   ["living", "dining", "kitchen"]),# dining between living & kitchen
            ("balcony_zone",  ["balcony"]),                    # highest Y — rear wall
        ],
    }

    # ── Bathroom width hard cap ────────────────────────────────────────────
    BATHROOM_MAX_WIDTH = 2.0   # metres

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")

        if not self.api_key:
            print("⚠️  GROQ_API_KEY not found. Using mock layout generator.")
            self.enabled = False
            return

        self.enabled = True
        self.client = Groq(api_key=self.api_key)
        self.models = [
            "llama-3.3-70b-versatile",
            "moonshotai/kimi-k2-instruct-0905",
            "gemma2-9b-it",
            "qwen-2.5-32b",
        ]

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    def generate_apartment_building(
        self,
        total_floors: int,
        flats_per_floor: int,
        flat_type: str,
        total_area_per_flat: float,
        requirements: dict,
        constraints: dict,
    ) -> dict:
        """Generate a full multi-floor apartment building layout."""
        plot_width   = constraints.get("plot_width",  25)
        plot_length  = constraints.get("plot_length", 20)
        setbacks     = constraints.get("setbacks", {"front": 3, "rear": 3, "side": 1.5})
        floor_height = constraints.get("floor_height", 3.0)
        corridor_w   = requirements.get("corridor_width", 1.5)

        avail_w = plot_width  - setbacks.get("side",  1.5) * 2 - self.WALL_THICKNESS * 2
        avail_l = plot_length - setbacks.get("front", 3.0) - setbacks.get("rear", 3.0) - self.WALL_THICKNESS * 2

        flat_w = (avail_w - (flats_per_floor - 1) * self.WALL_THICKNESS) / flats_per_floor
        flat_l = avail_l - corridor_w - self.WALL_THICKNESS
        max_flat_area = flat_w * flat_l

        target_area = min(total_area_per_flat, max_flat_area * 0.9)
        print(f"📐 Target area/flat: {target_area:.1f} sqm  (max possible: {max_flat_area:.1f})")

        # Stable but unique seed per run
        random.seed(int(target_area * 1000) + int(time.time() * 1000) % 9999)

        room_sizes = self.generate_room_sizes(
            flat_type=flat_type,
            total_area=target_area,
            requirements=requirements,
            plot_aspect_ratio=plot_width / max(plot_length, 1e-3),
        )

        floors = []
        for floor_idx in range(total_floors):
            floor_layout = self.generate_floor_layout(
                floor_number=floor_idx,
                flat_count=flats_per_floor,
                flat_type=flat_type,
                room_sizes=room_sizes,
                constraints={**constraints, "corridor_width": corridor_w},
            )
            floors.append(floor_layout)

        return {
            "floors": floors,
            "floor_height": floor_height,
            "total_floors": total_floors,
        }

    def generate_room_sizes(
        self,
        flat_type: str,
        total_area: float,
        requirements: dict,
        plot_aspect_ratio: float = 1.0,
    ) -> dict:
        """Return a dict of {room_name: {width, length}} for one flat."""
        if flat_type not in self.ROOM_PERCENTAGES:
            flat_type = "2BHK"

        percentages = self.ROOM_PERCENTAGES[flat_type]
        min_sizes   = self.MIN_ROOM_SIZES[flat_type]
        max_sizes   = self.MAX_ROOM_SIZES[flat_type]

        # Target areas — rooms only get 88 % of flat area (walls take the rest)
        room_areas = {r: total_area * p for r, p in percentages.items()}

        if not self.enabled:
            return self._generate_mock_room_sizes(flat_type, room_areas, min_sizes, max_sizes)

        prompt = self._build_room_prompt(
            flat_type, room_areas, min_sizes, max_sizes, requirements, plot_aspect_ratio
        )
        messages = [
            {"role": "system", "content": "You are an expert architectural designer. Respond with valid JSON only."},
            {"role": "user",   "content": prompt},
        ]

        for model in self.models:
            print(f"🤖 Trying {model} for room sizes …")
            resp = self._call_groq_api(messages, model)
            if resp:
                sizes = self._parse_room_response(resp, room_areas, min_sizes, max_sizes)
                if sizes:
                    print(f"✅ Room sizes from {model}")
                    return sizes
            time.sleep(0.5)

        print("⚠️  AI failed — using mock room sizes")
        return self._generate_mock_room_sizes(flat_type, room_areas, min_sizes, max_sizes)

    def generate_floor_layout(
        self,
        floor_number: int,
        flat_count: int,
        flat_type: str,
        room_sizes: dict,
        constraints: dict,
    ) -> dict:
        """Place all rooms for one floor using zone-based 2-D grid placement."""
        plot_width   = constraints.get("plot_width",  25)
        plot_length  = constraints.get("plot_length", 20)
        setbacks     = constraints.get("setbacks", {"front": 3, "rear": 3, "side": 1.5})
        corridor_w   = constraints.get("corridor_width", 1.5)

        avail_w = plot_width  - setbacks.get("side",  1.5) * 2 - self.WALL_THICKNESS * 2
        avail_l = plot_length - setbacks.get("front", 3.0) - setbacks.get("rear", 3.0) - self.WALL_THICKNESS * 2

        corridor_y = setbacks.get("front", 3.0) + self.WALL_THICKNESS
        flat_l     = avail_l - corridor_w - self.WALL_THICKNESS
        flat_w     = (avail_w - (flat_count - 1) * self.WALL_THICKNESS) / flat_count

        corridor = {
            "x":      setbacks.get("side", 1.5) + self.WALL_THICKNESS,
            "y":      corridor_y,
            "width":  avail_w,
            "length": corridor_w,
        }

        # 1. Cap bathroom widths then normalise every zone to flat_w
        sized = self._cap_bathroom_widths(room_sizes)
        sized = self._normalize_all_zones(sized, flat_w, flat_type)

        # 2. Calculate zone heights that sum to flat_l
        zone_heights = self._calculate_zone_heights(sized, flat_l, flat_type)

        flats = []
        for i in range(flat_count):
            flat_x = (
                setbacks.get("side", 1.5)
                + self.WALL_THICKNESS
                + i * (flat_w + self.WALL_THICKNESS)
            )
            flat_y = corridor_y + corridor_w + self.WALL_THICKNESS

            rooms = self._place_rooms(flat_x, flat_y, flat_w, flat_l,
                                      sized, zone_heights, flat_type)
            self._validate_layout(flat_x, flat_y, flat_w, flat_l, rooms)

            flats.append({
                "x": round(flat_x, 3),
                "y": round(flat_y, 3),
                "width":  round(flat_w, 3),
                "length": round(flat_l, 3),
                "rooms":  rooms,
            })

        return {"corridor": corridor, "flats": flats}

    # ══════════════════════════════════════════════════════════════════════
    # ZONE PLACEMENT ENGINE
    # ══════════════════════════════════════════════════════════════════════

    def _place_rooms(
        self,
        flat_x: float, flat_y: float,
        flat_w: float, flat_l: float,
        sizes: dict, zone_heights: List[float],
        flat_type: str,
    ) -> List[dict]:
        """
        Place rooms top-to-bottom by zone.
        Zone order: Balcony → Living+Kitchen → Bedrooms → Dining → Passage
        """
        zones  = self.ZONES.get(flat_type, self.ZONES["2BHK"])
        rooms  = []
        y_cur  = flat_y

        for zone_idx, (zone_name, zone_rooms) in enumerate(zones):
            zone_h = zone_heights[zone_idx]
            x_cur  = flat_x

            if len(zone_rooms) == 1:
                # Full-width room
                rname = zone_rooms[0]
                if rname in sizes:
                    rooms.append({
                        "name":   rname,
                        "x":      round(x_cur, 3),
                        "y":      round(y_cur, 3),
                        "width":  round(flat_w, 3),
                        "length": round(zone_h, 3),
                    })
            else:
                # Side-by-side rooms — widths already normalised to flat_w
                for rname in zone_rooms:
                    if rname not in sizes:
                        continue
                    rw = sizes[rname]["width"]
                    # last room: fill any floating-point remainder
                    if rname == zone_rooms[-1] or zone_rooms.index(rname) == len(zone_rooms) - 1:
                        rw = flat_x + flat_w - x_cur
                    rooms.append({
                        "name":   rname,
                        "x":      round(x_cur, 3),
                        "y":      round(y_cur, 3),
                        "width":  round(rw, 3),
                        "length": round(zone_h, 3),
                    })
                    x_cur += rw

            y_cur += zone_h

        return rooms

    # ══════════════════════════════════════════════════════════════════════
    # WIDTH NORMALISATION
    # ══════════════════════════════════════════════════════════════════════

    def _cap_bathroom_widths(self, room_sizes: dict) -> dict:
        """Ensure no bathroom is wider than BATHROOM_MAX_WIDTH."""
        sizes = {k: v.copy() for k, v in room_sizes.items()}
        for key in list(sizes.keys()):
            if "bath" in key:
                sizes[key]["width"] = min(sizes[key]["width"], self.BATHROOM_MAX_WIDTH)
        return sizes

    def _normalize_all_zones(self, room_sizes: dict, flat_w: float, flat_type: str) -> dict:
        """
        Scale room widths so every zone row fills exactly flat_w.
        Full-width zones (balcony, dining, passage) are set directly.
        Side-by-side zones are proportionally scaled.
        """
        sizes = {k: v.copy() for k, v in room_sizes.items()}
        zones = self.ZONES.get(flat_type, self.ZONES["2BHK"])

        for _, zone_rooms in zones:
            present = [r for r in zone_rooms if r in sizes]
            if not present:
                continue

            if len(present) == 1:
                sizes[present[0]]["width"] = flat_w
            else:
                total_w = sum(sizes[r]["width"] for r in present)
                if total_w > 0:
                    scale = flat_w / total_w
                    for r in present:
                        sizes[r]["width"] = round(sizes[r]["width"] * scale, 3)

        return sizes

    # ══════════════════════════════════════════════════════════════════════
    # ZONE HEIGHT CALCULATION
    # ══════════════════════════════════════════════════════════════════════

    def _calculate_zone_heights(
        self, sizes: dict, flat_l: float, flat_type: str
    ) -> List[float]:
        """
        Derive a zone height for each zone so they sum to flat_l.

        Height rules:
          balcony_zone   → balcony.length           (min 1.8 m)
          living_zone    → max(living, kitchen)     (min 4.0 m)
          bedroom_zone   → max(bed1, bed2)          (min 4.0 m)
          dining_zone    → dining.length            (min 2.5 m)
          passage_zone   → passage.length           (min 1.8 m)
        """
        zones = self.ZONES.get(flat_type, self.ZONES["2BHK"])

        raw_heights = []
        for zone_name, zone_rooms in zones:
            present = [r for r in zone_rooms if r in sizes]
            if not present:
                raw_heights.append(2.0)
                continue

            if "balcony" in zone_name:
                h = sizes.get("balcony", {}).get("length", 1.8)
                h = max(h, 1.8)
            elif "living" in zone_name:
                h = max(sizes.get(r, {}).get("length", 4.0) for r in present)
                h = max(h, 4.0)
            elif "bedroom" in zone_name:
                h = max(sizes.get(r, {}).get("length", 4.0)
                        for r in present if "bed" in r)
                h = max(h, 4.0)
            elif "dining" in zone_name:
                h = sizes.get("dining", {}).get("length", 2.5)
                h = max(h, 2.5)
            elif "passage" in zone_name:
                h = sizes.get("passage", {}).get("length", 1.8)
                h = max(h, 1.8)
            else:
                h = 3.0

            raw_heights.append(h)

        # Scale so total == flat_l
        total = sum(raw_heights)
        if total <= 0:
            return [flat_l / len(raw_heights)] * len(raw_heights)

        scale = flat_l / total
        scaled = [round(h * scale, 3) for h in raw_heights]

        # Fix rounding residual on the last zone
        diff = flat_l - sum(scaled)
        scaled[-1] = round(scaled[-1] + diff, 3)

        return scaled

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION
    # ══════════════════════════════════════════════════════════════════════

    def _validate_layout(
        self, flat_x, flat_y, flat_w, flat_l, rooms: List[dict]
    ):
        flat_area    = flat_w * flat_l
        placed_area  = sum(r["width"] * r["length"] for r in rooms)
        coverage     = placed_area / flat_area if flat_area > 0 else 0

        if not (0.78 <= coverage <= 1.02):
            print(f"⚠️  Coverage {coverage:.0%} outside [78 %–102 %]")

        tol = 0.05
        for r in rooms:
            if r["x"] < flat_x - tol:
                print(f"⚠️  {r['name']} overflows left  (x={r['x']:.2f} flat_x={flat_x:.2f})")
            if r["x"] + r["width"] > flat_x + flat_w + tol:
                print(f"⚠️  {r['name']} overflows right (x+w={r['x']+r['width']:.2f} limit={flat_x+flat_w:.2f})")
            if r["y"] < flat_y - tol:
                print(f"⚠️  {r['name']} overflows top")
            if r["y"] + r["length"] > flat_y + flat_l + tol:
                print(f"⚠️  {r['name']} overflows bottom")

        # Overlap check
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                ox = a["x"] < b["x"] + b["width"]  - tol and b["x"] < a["x"] + a["width"]  - tol
                oy = a["y"] < b["y"] + b["length"] - tol and b["y"] < a["y"] + a["length"] - tol
                if ox and oy:
                    print(f"⚠️  OVERLAP: {a['name']} ↔ {b['name']}")

    # ══════════════════════════════════════════════════════════════════════
    # AI HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _call_groq_api(self, messages: list, model: str) -> Optional[str]:
        try:
            resp = self.client.chat.completions.create(
                messages=messages,
                model=model,
                max_tokens=3000,
                temperature=0.7,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"⚠️  Groq error ({model}): {str(e)[:120]}")
            return None

    def _build_room_prompt(
        self, flat_type, room_areas, min_sizes, max_sizes, requirements, aspect_ratio
    ) -> str:
        return f"""
Generate realistic room dimensions for a {flat_type} flat.

ZONE LAYOUT (BOTTOM = entrance/corridor → TOP = rear/balcony wall):
  Zone 1 BOTTOM: Passage  — full width, shallow (1.8–2.2 m deep), faces corridor
  Zone 2       : Bedroom1 | Bathroom1 | Bedroom2 | Bathroom2  — side by side
  Zone 3       : Living | Dining | Kitchen  — side by side (Dining between Living & Kitchen)
  Zone 4 TOP   : Balcony  — full width, narrow (1.8–2.5 m deep), rear external wall

TARGET AREAS (sqm): {json.dumps(room_areas, indent=2)}
MINIMUM AREAS (sqm): {json.dumps(min_sizes,  indent=2)}
MAXIMUM AREAS (sqm): {json.dumps(max_sizes,  indent=2)}

CRITICAL DIMENSION RULES:
- Bathroom width MUST NOT exceed 2.0 m
- Balcony depth (length) between 1.8–2.5 m
- Passage depth (length) between 1.8–2.2 m
- Living width > Dining width, Kitchen width (living is widest)
- Bedroom width > Bathroom width
- Living, Dining, Kitchen must have the SAME length (they share one zone row)
- Plot aspect ratio (W/L): {aspect_ratio:.2f}

Return ONLY JSON. Example for 2BHK:
{{
  "living":    {{"width": 9.0,  "length": 5.5}},
  "dining":    {{"width": 4.0,  "length": 5.5}},
  "kitchen":   {{"width": 5.0,  "length": 5.5}},
  "bedroom1":  {{"width": 6.5,  "length": 5.0}},
  "bathroom1": {{"width": 2.0,  "length": 5.0}},
  "bedroom2":  {{"width": 5.5,  "length": 5.0}},
  "bathroom2": {{"width": 1.8,  "length": 5.0}},
  "balcony":   {{"width": 18.0, "length": 2.0}},
  "passage":   {{"width": 18.0, "length": 2.0}}
}}
"""

    def _parse_room_response(
        self, response: str, room_areas: dict, min_sizes: dict, max_sizes: dict
    ) -> Optional[dict]:
        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            sizes = json.loads(response)

            for room in room_areas:
                if room not in sizes:
                    print(f"⚠️  AI missing room: {room}")
                    return None

            return sizes
        except Exception as e:
            print(f"⚠️  Parse error: {e}")
            return None

    # ══════════════════════════════════════════════════════════════════════
    # MOCK FALLBACK
    # ══════════════════════════════════════════════════════════════════════

    def _generate_mock_room_sizes(
        self, flat_type: str, room_areas: dict, min_sizes: dict, max_sizes: dict
    ) -> dict:
        """Deterministic-ish fallback room sizes with correct aspect ratios."""
        sizes = {}

        for room, target in room_areas.items():
            min_a = min_sizes.get(room, 3)
            max_a = max_sizes.get(room, 30)
            area  = max(min_a, min(max_a, target * random.uniform(0.92, 1.08)))

            if "living" in room:
                # Wide and moderately deep
                w = math.sqrt(area * 1.4)
                l = area / w
            elif "bedroom" in room:
                # Slightly wider than deep
                w = math.sqrt(area * 1.1)
                l = area / w
            elif "kitchen" in room:
                # Narrower but deep
                w = math.sqrt(area * 0.75)
                l = area / w
            elif "bath" in room:
                # Hard cap at 2.0 m wide
                w = min(self.BATHROOM_MAX_WIDTH, math.sqrt(area * 0.55))
                l = area / w
            elif "balcony" in room:
                l = min(2.2, area / max(area / 2.2, 1.0))
                w = area / l
            elif "passage" in room:
                l = min(2.0, area / max(area / 2.0, 1.0))
                w = area / l
            elif "dining" in room:
                w = math.sqrt(area * 1.3)
                l = area / w
            else:
                w = math.sqrt(area)
                l = area / w

            sizes[room] = {
                "width":  round(max(1.2, w), 2),
                "length": round(max(1.2, l), 2),
            }

        print(f"📐 Mock sizes generated for {flat_type}")
        return sizes

    # ══════════════════════════════════════════════════════════════════════
    # COMMERCIAL (unchanged from before)
    # ══════════════════════════════════════════════════════════════════════

    def generate_commercial_building(
        self,
        total_floors: int,
        floorplate_depth: float,
        requirements: dict,
        constraints: dict,
    ) -> dict:
        plot_width  = constraints.get("plot_width",  25.0)
        plot_length = constraints.get("plot_length", 40.0)
        setbacks    = constraints.get("setbacks", {"front": 6.0, "rear": 6.0, "side": 3.0})

        avail_w = plot_width  - setbacks.get("side",  3.0) * 2
        avail_l = plot_length - setbacks.get("front", 6.0) - setbacks.get("rear", 6.0)

        fp_l = min(floorplate_depth or avail_l, avail_l)
        fp_w = avail_w

        corridor_w = requirements.get("corridor_width", 2.0)
        core_w     = requirements.get("core_width",     8.0)
        core_l     = requirements.get("core_length",    10.0)

        flat_x = setbacks.get("side",  3.0)
        flat_y = setbacks.get("front", 6.0)

        floors = []
        for floor_idx in range(total_floors):
            core_x   = flat_x + (fp_w - core_w) / 2.0
            core_y   = flat_y + corridor_w
            office_y = flat_y + corridor_w + core_l
            off_l    = max(fp_l - corridor_w - core_l, 4.0)

            rooms = [
                {"name": "corridor",      "x": flat_x, "y": flat_y,   "width": fp_w,  "length": corridor_w},
                {"name": "core",          "x": core_x, "y": core_y,   "width": core_w,"length": core_l},
                {"name": "fire_escape_1", "x": flat_x, "y": flat_y,   "width": 3.0,   "length": 4.0},
                {"name": "fire_escape_2", "x": flat_x + fp_w - 3.0, "y": flat_y, "width": 3.0, "length": 4.0},
                {"name": "office_area",   "x": flat_x, "y": office_y, "width": fp_w,  "length": off_l},
            ]

            floors.append({
                "floor": floor_idx,
                "flats": [{"x": flat_x, "y": flat_y, "width": fp_w,
                           "length": fp_l, "rooms": rooms}],
            })

        return {
            "building_width":  avail_w,
            "building_length": avail_l,
            "floor_height":    constraints.get("floor_height", 3.5),
            "floors":          floors,
        }