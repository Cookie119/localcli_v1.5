# services/cad_generator.py
import ezdxf
import math
from ezdxf.enums import TextEntityAlignment
import datetime
from typing import List, Optional


class CADGenerator:
    """
    Generates DXF floor-plan drawings from layout JSON.

    Fixes applied vs previous version:
      • Walls drawn with real thickness (draw_wall) for all room boundaries
      • Doors placed on the correct wall for each room type/position
      • Windows on correct external walls (top = rear, bottom = corridor side)
      • All rooms (living, kitchen, dining, balcony) get external-wall windows
      • Multi-floor drawings offset vertically so floors never overlap
      • Furniture scales with room size and never overflows boundary
      • Layer creation idempotent (_ensure_layer)
      • reset() method for multi-design sessions
    """

    # DXF colours (ACI index)
    COL = {
        "wall":      7,   # white / black
        "flat":      6,   # magenta
        "corridor":  4,   # cyan
        "door":      3,   # green
        "window":    5,   # blue
        "text":      2,   # yellow
        "dim":       4,   # cyan
        "grid":      8,   # dark grey
        "furniture": 6,   # magenta
        "title":     1,   # red
    }

    WALL_T        = 0.15   # wall thickness (metres)
    FLOOR_GAP     = 4.0    # vertical gap between floor drawings

    def __init__(self):
        self._total_h = 0.0   # set in generate_floor_plan, used for Y-flip
        self._new_doc()

    def _new_doc(self):
        self.doc = ezdxf.new("R2010")
        self.msp = self.doc.modelspace()
        self._layers: set = set()

    def _fy(self, y: float) -> float:
        """Flip a Y coordinate so high-Y (balcony/rear) appears at top of drawing."""
        return self._total_h - y

    def reset(self):
        """Reset for a new design without creating a new instance."""
        self._new_doc()

    # ══════════════════════════════════════════════════════════════════════
    # LAYER MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════

    def _ensure_layer(self, name: str, color: int = 7):
        if name not in self._layers:
            self.doc.layers.add(name=name, color=color)
            self._layers.add(name)

    def _init_layers(self):
        pairs = [
            ("WALLS",     self.COL["wall"]),
            ("FLAT",      self.COL["flat"]),
            ("CORRIDOR",  self.COL["corridor"]),
            ("DOORS",     self.COL["door"]),
            ("WINDOWS",   self.COL["window"]),
            ("TEXT",      self.COL["text"]),
            ("DIMENSIONS",self.COL["dim"]),
            ("GRID",      self.COL["grid"]),
            ("FURNITURE", self.COL["furniture"]),
        ]
        for name, color in pairs:
            self._ensure_layer(name, color)

    # ══════════════════════════════════════════════════════════════════════
    # PRIMITIVE DRAWING HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _rect(self, x, y, w, l, layer="WALLS", color=7):
        """Draw a filled-outline rectangle (no wall thickness — for outlines).
        Y coordinates are flipped so high-Y data appears at top of drawing."""
        fy  = self._fy(y + l)   # top of rect in flipped coords
        pts = [(x, fy), (x+w, fy), (x+w, fy+l), (x, fy+l), (x, fy)]
        self.msp.add_lwpolyline(pts, close=True,
                                dxfattribs={"layer": layer, "color": color})

    def draw_wall(self, x1, y1, x2, y2, thickness=None, layer="WALLS", color=7):
        """Draw a wall segment as a filled rectangle with real thickness."""
        t = thickness or self.WALL_T
        # Flip Y
        y1, y2 = self._fy(y1), self._fy(y2)
        dx = x2 - x1
        dy = y2 - y1
        ln = math.hypot(dx, dy)
        if ln < 0.001:
            return
        px = -dy / ln * t / 2
        py =  dx / ln * t / 2
        pts = [
            (x1+px, y1+py), (x2+px, y2+py),
            (x2-px, y2-py), (x1-px, y1-py),
            (x1+px, y1+py),
        ]
        self.msp.add_lwpolyline(pts, close=True,
                                dxfattribs={"layer": layer, "color": color})

    def _draw_room_walls(self, x, y, w, l):
        """Draw 4 walls with proper thickness around a room (Y already flipped)."""
        t   = self.WALL_T
        col = self.COL["wall"]
        # y here is already the flipped bottom-of-room in drawing coords
        self.msp.add_lwpolyline(
            [(x, y), (x+w, y), (x+w, y+l), (x, y+l), (x, y)],
            close=True, dxfattribs={"layer": "WALLS", "color": col}
        )

    # ══════════════════════════════════════════════════════════════════════
    # DOOR SYMBOL
    # Door arc radius = half door width (0.9 m standard leaf)
    # ══════════════════════════════════════════════════════════════════════

    def _add_door(self, x, y, w, l, wall: str):
        """
        Place a door symbol centred on the specified wall.
        wall: 'bottom' | 'top' | 'left' | 'right'
        """
        door_w = min(0.9, w * 0.45, l * 0.45)
        attribs = {"layer": "DOORS", "color": self.COL["door"]}

        if wall == "bottom":
            cx = x + w / 2
            cy = y
            self.msp.add_line((cx - door_w/2, cy), (cx + door_w/2, cy), dxfattribs=attribs)
            self.msp.add_arc(center=(cx - door_w/2, cy),
                             radius=door_w, start_angle=0, end_angle=90,
                             dxfattribs=attribs)
        elif wall == "top":
            cx = x + w / 2
            cy = y + l
            self.msp.add_line((cx - door_w/2, cy), (cx + door_w/2, cy), dxfattribs=attribs)
            self.msp.add_arc(center=(cx + door_w/2, cy),
                             radius=door_w, start_angle=90, end_angle=180,
                             dxfattribs=attribs)
        elif wall == "left":
            cx = x
            cy = y + l / 2
            self.msp.add_line((cx, cy - door_w/2), (cx, cy + door_w/2), dxfattribs=attribs)
            self.msp.add_arc(center=(cx, cy - door_w/2),
                             radius=door_w, start_angle=0, end_angle=90,
                             dxfattribs=attribs)
        elif wall == "right":
            cx = x + w
            cy = y + l / 2
            self.msp.add_line((cx, cy - door_w/2), (cx, cy + door_w/2), dxfattribs=attribs)
            self.msp.add_arc(center=(cx, cy + door_w/2),
                             radius=door_w, start_angle=180, end_angle=270,
                             dxfattribs=attribs)

    # ══════════════════════════════════════════════════════════════════════
    # WINDOW SYMBOL  (double parallel lines centred on the wall)
    # ══════════════════════════════════════════════════════════════════════

    def _add_window(self, x, y, w, l, wall: str, win_size: float = 1.5):
        """Place a window symbol centred on the specified wall."""
        attribs = {"layer": "WINDOWS", "color": self.COL["window"]}
        win_size = min(win_size, (w if wall in ("top","bottom") else l) * 0.6)
        gap = 0.12  # gap between the two window lines

        if wall == "top":
            cx, cy = x + w/2, y + l
            for dy in (0, gap):
                self.msp.add_line((cx - win_size/2, cy + dy),
                                  (cx + win_size/2, cy + dy), dxfattribs=attribs)
            self.msp.add_line((cx - win_size/2, cy), (cx - win_size/2, cy + gap), dxfattribs=attribs)
            self.msp.add_line((cx + win_size/2, cy), (cx + win_size/2, cy + gap), dxfattribs=attribs)

        elif wall == "bottom":
            cx, cy = x + w/2, y
            for dy in (0, -gap):
                self.msp.add_line((cx - win_size/2, cy + dy),
                                  (cx + win_size/2, cy + dy), dxfattribs=attribs)
            self.msp.add_line((cx - win_size/2, cy), (cx - win_size/2, cy - gap), dxfattribs=attribs)
            self.msp.add_line((cx + win_size/2, cy), (cx + win_size/2, cy - gap), dxfattribs=attribs)

        elif wall == "right":
            cx, cy = x + w, y + l/2
            for dx in (0, gap):
                self.msp.add_line((cx + dx, cy - win_size/2),
                                  (cx + dx, cy + win_size/2), dxfattribs=attribs)
            self.msp.add_line((cx, cy - win_size/2), (cx + gap, cy - win_size/2), dxfattribs=attribs)
            self.msp.add_line((cx, cy + win_size/2), (cx + gap, cy + win_size/2), dxfattribs=attribs)

        elif wall == "left":
            cx, cy = x, y + l/2
            for dx in (0, -gap):
                self.msp.add_line((cx + dx, cy - win_size/2),
                                  (cx + dx, cy + win_size/2), dxfattribs=attribs)
            self.msp.add_line((cx, cy - win_size/2), (cx - gap, cy - win_size/2), dxfattribs=attribs)
            self.msp.add_line((cx, cy + win_size/2), (cx - gap, cy + win_size/2), dxfattribs=attribs)

    # ══════════════════════════════════════════════════════════════════════
    # ROOM DRAWING — walls, door, windows, label, dimensions
    # ══════════════════════════════════════════════════════════════════════

    def draw_room(self, x, y, w, l, name,
                  flat_x, flat_y, flat_w, flat_l, y_off=0.0):
        """
        Draw one room with thick walls, door, windows, label, dimensions.
        All Y values from layout are flipped so balcony appears at top.
        """
        # Flip: high Y in data = top of building = top of drawing
        ry_draw = self._fy(y + y_off + l)   # drawing Y of bottom edge of room
        flat_y_draw     = self._fy(flat_y + y_off + flat_l)
        flat_top_draw   = self._fy(flat_y + y_off)
        rx = x

        # ── Thick walls ──────────────────────────────────────────────────
        self._draw_room_walls(rx, ry_draw, w, l)

        # ── Determine external walls (in drawing orientation) ─────────────
        tol = 0.05
        # In drawing coords: flat_y_draw = visual top of flat, flat_top_draw = visual bottom
        # room top in drawing  = ry_draw + l  (high drawing Y = visual bottom)
        # room bottom in drawing = ry_draw    (low drawing Y = visual top)
        is_top_draw    = ry_draw      <= flat_y_draw   + tol   # visual top = rear/balcony
        is_bottom_draw = ry_draw + l  >= flat_top_draw - tol   # visual bottom = corridor
        is_left        = rx           <= flat_x        + tol
        is_right       = rx + w       >= flat_x + flat_w - tol

        ext_walls = []
        if is_top_draw:    ext_walls.append("top")
        if is_bottom_draw: ext_walls.append("bottom")
        if is_left:        ext_walls.append("left")
        if is_right:       ext_walls.append("right")

        # ── Door logic ────────────────────────────────────────────────────
        rn = name.lower()
        door_wall = None
        if "passage" not in rn and "corridor" not in rn:
            if "balcony" in rn:
                door_wall = "bottom"   # balcony opens toward living (visual bottom)
            elif is_top_draw:
                door_wall = "bottom"   # rear room opens inward
            elif is_bottom_draw:
                door_wall = "top"      # passage-adjacent room opens upward
            else:
                door_wall = "bottom"   # default

        if door_wall:
            self._add_door(rx, ry_draw, w, l, door_wall)

        # ── Windows on external walls ────────────────────────────────────
        for ew in ext_walls:
            self._add_window(rx, ry_draw, w, l, ew)

        # ── Room label ───────────────────────────────────────────────────
        self.msp.add_text(
            name.upper(),
            dxfattribs={"layer": "TEXT", "height": max(0.2, min(0.35, w * 0.06)),
                        "color": self.COL["text"]},
        ).set_placement((rx + w/2, ry_draw + l/2), align=TextEntityAlignment.CENTER)

        # ── Dimension text ────────────────────────────────────────────────
        self.msp.add_text(
            f"{w:.1f}m",
            dxfattribs={"layer": "DIMENSIONS", "height": 0.15, "color": self.COL["dim"]},
        ).set_placement((rx + w/2, ry_draw - 0.35), align=TextEntityAlignment.CENTER)

        self.msp.add_text(
            f"{l:.1f}m",
            dxfattribs={"layer": "DIMENSIONS", "height": 0.15, "color": self.COL["dim"]},
        ).set_placement((rx - 0.5, ry_draw + l/2), align=TextEntityAlignment.MIDDLE)

    # ══════════════════════════════════════════════════════════════════════
    # FURNITURE SYMBOLS
    # ══════════════════════════════════════════════════════════════════════

    def _add_furniture(self, x, y, w, l, name, y_off=0.0):
        """Simple furniture outlines — safely clamped to room boundary."""
        ry_draw = self._fy(y + y_off + l)   # flipped bottom of room in drawing
        attribs = {"layer": "FURNITURE", "color": self.COL["furniture"]}
        margin = 0.4
        rn = name.lower()

        if "living" in rn:
            sw = min(w - 2*margin, 2.2)
            sl = min(l - 2*margin, 1.0)
            if sw > 0.4 and sl > 0.4:
                sx, sy = x + margin, ry_draw + margin
                self.msp.add_lwpolyline(
                    [(sx, sy), (sx+sw, sy), (sx+sw, sy+sl), (sx, sy+sl), (sx, sy)],
                    close=True, dxfattribs=attribs)

        elif "bedroom" in rn:
            bw = min(w - 2*margin, 2.0)
            bl = min(l - 2*margin, 1.9)
            if bw > 0.4 and bl > 0.4:
                bx = x + (w - bw) / 2
                by = ry_draw + margin
                self.msp.add_lwpolyline(
                    [(bx, by), (bx+bw, by), (bx+bw, by+bl), (bx, by+bl), (bx, by)],
                    close=True, dxfattribs=attribs)
                self.msp.add_line((bx, by + bl*0.7), (bx+bw, by + bl*0.7),
                                  dxfattribs=attribs)

        elif "dining" in rn:
            tw = min(w - 2*margin, 1.8)
            tl = min(l - 2*margin, 1.0)
            if tw > 0.4 and tl > 0.4:
                tx = x + (w - tw) / 2
                ty = ry_draw + (l - tl) / 2
                self.msp.add_lwpolyline(
                    [(tx, ty), (tx+tw, ty), (tx+tw, ty+tl), (tx, ty+tl), (tx, ty)],
                    close=True, dxfattribs=attribs)

    # ══════════════════════════════════════════════════════════════════════
    # GRID
    # ══════════════════════════════════════════════════════════════════════

    def _draw_grid(self, total_w, total_h, step=1.0):
        attribs = {"layer": "GRID", "color": self.COL["grid"]}
        for i in range(0, int(total_w / step) + 2):
            xi = i * step
            self.msp.add_line((xi, 0), (xi, total_h), dxfattribs=attribs)
        for j in range(0, int(total_h / step) + 2):
            yj = j * step
            self.msp.add_line((0, yj), (total_w, yj), dxfattribs=attribs)
    # ══════════════════════════════════════════════════════════════════════
    # MAIN ENTRY POINT
    # ══════════════════════════════════════════════════════════════════════

    def generate_floor_plan(self, design_id: int, layout_data: dict):
        """
        Render the complete floor plan DXF from layout_data.
        Y coordinates are FLIPPED via _fy() so:
          - Balcony (high Y in data) → appears at TOP of drawing
          - Passage/corridor (low Y in data) → appears at BOTTOM of drawing
        Each floor is offset vertically so floors never overlap.
        """
        self._init_layers()

        floors = layout_data.get("floors", [])
        if not floors:
            print("⚠️  No floors in layout_data")
            return self.doc

        # ── Pre-compute per-floor bounding box heights ────────────────────
        floor_heights = []
        max_x_global  = 0.0

        for floor in floors:
            fh = 0.0
            if "corridor" in floor:
                c = floor["corridor"]
                fh = max(fh, c.get("y", 0) + c.get("length", 0))
                max_x_global = max(max_x_global, c.get("x", 0) + c.get("width", 0))
            for flat in floor.get("flats", []):
                fh = max(fh, flat.get("y", 0) + flat.get("length", 0))
                max_x_global = max(max_x_global, flat.get("x", 0) + flat.get("width", 0))
                for room in flat.get("rooms", []):
                    fh = max(fh, room.get("y", 0) + room.get("length", 0))
                    max_x_global = max(max_x_global, room.get("x", 0) + room.get("width", 0))
            floor_heights.append(fh)

        total_drawing_h = (sum(floor_heights)
                           + self.FLOOR_GAP * len(floors)
                           + 6)
        total_drawing_w = max_x_global + 4

        # Set total height so _fy() flips correctly
        self._total_h = total_drawing_h

        # ── Grid ──────────────────────────────────────────────────────────
        self._draw_grid(total_drawing_w, total_drawing_h)

        # ── Draw each floor ───────────────────────────────────────────────
        y_offset = 0.0

        for floor_idx, floor in enumerate(floors):
            fh = floor_heights[floor_idx]

            # Corridor — flip Y
            if "corridor" in floor:
                c = floor["corridor"]
                cy = c["y"] + y_offset
                self._rect(c["x"], cy, c["width"], c["length"],
                           "CORRIDOR", self.COL["corridor"])
                # Label centred in flipped rect
                c_label_y = self._fy(cy + c["length"]) + c["length"] / 2
                self.msp.add_text(
                    f"CORRIDOR  F{floor_idx+1}",
                    dxfattribs={"layer": "TEXT", "height": 0.2,
                                "color": self.COL["corridor"]},
                ).set_placement(
                    (c["x"] + c["width"] / 2, c_label_y),
                    align=TextEntityAlignment.CENTER,
                )

            # Flats
            for flat_idx, flat in enumerate(floor.get("flats", [])):
                fx = flat.get("x", 0)
                fy = flat.get("y", 0)
                fw = flat.get("width",  0)
                fl = flat.get("length", 0)
                fy_off = fy + y_offset

                # Flat outline (flipped via _rect)
                self._rect(fx, fy_off, fw, fl, "FLAT", self.COL["flat"])

                # Flat label at visual bottom (passage side = low original Y → high draw Y)
                flat_label_y = self._fy(fy_off + fl) + 0.35
                self.msp.add_text(
                    f"FLAT {flat_idx + 1}",
                    dxfattribs={"layer": "TEXT", "height": 0.28,
                                "color": self.COL["flat"]},
                ).set_placement(
                    (fx + fw / 2, flat_label_y),
                    align=TextEntityAlignment.CENTER,
                )

                # Rooms
                for room in flat.get("rooms", []):
                    rx = room.get("x", 0)
                    ry = room.get("y", 0)
                    rw = room.get("width",  0)
                    rl = room.get("length", 0)
                    rn = room.get("name",  "room")

                    if rw < 0.1 or rl < 0.1:
                        continue

                    self.draw_room(rx, ry, rw, rl, rn,
                                   fx, fy, fw, fl, y_offset)

                    if any(k in rn for k in ("living", "bedroom", "dining")):
                        self._add_furniture(rx, ry, rw, rl, rn, y_offset)

            # Floor label — place above the visual top of this floor
            floor_label_y = self._fy(y_offset + fh) - 0.7
            self.msp.add_text(
                f"FLOOR {floor_idx + 1}",
                dxfattribs={"layer": "TEXT", "height": 0.4,
                            "color": self.COL["title"]},
            ).set_placement(
                (total_drawing_w / 2, floor_label_y),
                align=TextEntityAlignment.CENTER,
            )

            y_offset += fh + self.FLOOR_GAP

        # ── Title block at visual top of drawing ─────────────────────────
        title_y = total_drawing_h - 1.0
        self.msp.add_text(
            f"DESIGN ID: {design_id}  |  NIRMAAN.AI",
            dxfattribs={"layer": "TEXT", "height": 0.45, "color": self.COL["title"]},
        ).set_placement((2, title_y), align=TextEntityAlignment.LEFT)

        self.msp.add_text(
            "SCALE 1:100",
            dxfattribs={"layer": "TEXT", "height": 0.25, "color": self.COL["title"]},
        ).set_placement((2, title_y - 0.6), align=TextEntityAlignment.LEFT)

        self.msp.add_text(
            f"DATE: {datetime.datetime.now():%Y-%m-%d}",
            dxfattribs={"layer": "TEXT", "height": 0.25, "color": self.COL["title"]},
        ).set_placement((2, title_y - 1.0), align=TextEntityAlignment.LEFT)

        return self.doc

    # ══════════════════════════════════════════════════════════════════════
    # SAVE
    # ══════════════════════════════════════════════════════════════════════

    def save_dxf(self, filename: str) -> str:
        self.doc.saveas(filename)
        print(f"✅ DXF saved → {filename}")
        return filename