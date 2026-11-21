# Regression fixture: a small side chair built from every basic modelkit builder.
# Parameters at the top, metres, Z up, front faces -Y. Run through bmod.py.
import modelkit as mk

SEAT_H = 0.45
SEAT = (0.44, 0.42, 0.03)
LEG_R = 0.016
BACK_H = 0.40

seat = mk.box("Seat", SEAT, (0, 0, SEAT_H - SEAT[2] / 2))
mk.finish(seat, bevel=0.003)
legs = []
for sx in (-1, 1):
    for sy in (-1, 1):
        x, y = sx * (SEAT[0] / 2 - 0.03), sy * (SEAT[1] / 2 - 0.03)
        name = f"Leg_{'F' if sy < 0 else 'B'}{'L' if sx < 0 else 'R'}"
        # legs run 3 mm into the seat (joints overlap in reality)
        h = SEAT_H - SEAT[2] + 0.003
        leg = mk.cylinder(name, LEG_R, h, (x, y, h / 2), radius_top=LEG_R * 0.8, segments=32)
        mk.finish(leg, bevel=0.002)
        legs.append(leg)
# turned finials on the back posts (lathe)
back_y = SEAT[1] / 2 - 0.03
for sx in (-1, 1):
    post = mk.cylinder(f"Post_{'L' if sx < 0 else 'R'}", LEG_R * 0.8, BACK_H,
                       (sx * (SEAT[0] / 2 - 0.03), back_y, SEAT_H - 0.003 + BACK_H / 2))
    mk.finish(post, bevel=0.002)
    mk.lathe(f"Finial_{'L' if sx < 0 else 'R'}",
             [(0, 0), (0.014, 0), (0.016, 0.01), (0.01, 0.025), (0.012, 0.035), (0, 0.045)],
             (sx * (SEAT[0] / 2 - 0.03), back_y, SEAT_H + BACK_H - 0.008), segments=32)
# bent backrest rail (tube mesh) between the posts
mk.tube("Back_Rail", [(-0.19, back_y, SEAT_H + 0.30), (0, back_y + 0.025, SEAT_H + 0.32),
                      (0.19, back_y, SEAT_H + 0.30)], 0.012)
# a cable kept as a curve (exercises curve bounds in the review framing)
cable = mk.tube("Cable", [(0.19, back_y, SEAT_H + 0.30), (0.25, back_y + 0.05, 0.4), (0.3, 0.1, 0.0)],
                0.003, kind="poly", to_mesh=False)
oak = mk.material("Oak", (0.45, 0.28, 0.15), roughness=0.55, variation=0.2)
for o in [seat] + legs:
    mk.assign(o, oak)
