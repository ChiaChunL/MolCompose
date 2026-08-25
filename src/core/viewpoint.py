"""Camera and partner placement for the two views an interface figure wants.

Both are standard in the literature and neither is reachable by dragging.

**Face-on** looks down the axis joining the two partners' interface centroids,
so the contact patch is presented as a footprint rather than edge-on. It is
the view for "what shape is this interface", and it is what you want with one
partner hidden.

**Open book** separates the partners along that axis and rotates each by a
half turn about a perpendicular, so both binding faces end up pointing at the
viewer at once. It is the view for "what does each side contribute", and it
is the one that is genuinely hard to set up by hand, because the two rotations
have to be about the same perpendicular axis in opposite senses.

The geometry is here, free of ChimeraX, because it is the part worth testing.
"""

import math
from dataclasses import dataclass

Vector = tuple[float, float, float]

# How far apart to place the two partners in an open-book view, as a multiple
# of the larger partner's radius. 1.2 leaves a clear gap without pushing them
# so far that the figure has to zoom out and lose the side chains.
OPEN_BOOK_GAP = 1.2


@dataclass(frozen=True)
class Placement:
    """One partner's rigid motion: turn `angle` about `axis` through `centre`,
    then translate by `shift`."""

    axis: Vector
    angle: float
    centre: Vector
    shift: Vector


def centroid(points) -> Vector:
    points = tuple(points)
    if not points:
        raise ValueError("cannot take the centroid of no points")
    count = len(points)
    return tuple(sum(p[i] for p in points) / count for i in range(3))


def subtract(a: Vector, b: Vector) -> Vector:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def norm(v: Vector) -> float:
    return math.sqrt(sum(component * component for component in v))


def normalise(v: Vector) -> Vector:
    length = norm(v)
    if length < 1e-9:
        raise ValueError(
            "the two groups' centroids coincide, so the interface has no axis"
        )
    return (v[0] / length, v[1] / length, v[2] / length)


def cross(a: Vector, b: Vector) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def interface_axis(points_a, points_b) -> Vector:
    """Unit vector from group A's interface centroid towards group B's.

    The interface plane is roughly perpendicular to this, which is what makes
    it the axis both views are built on.
    """
    return normalise(subtract(centroid(points_b), centroid(points_a)))


def perpendicular(axis: Vector) -> Vector:
    """Any unit vector at right angles to `axis`.

    Crossing with whichever cardinal direction the axis is least aligned to,
    so the cross product is never near-degenerate.
    """
    axis = normalise(axis)
    least = min(range(3), key=lambda i: abs(axis[i]))
    cardinal = tuple(1.0 if i == least else 0.0 for i in range(3))
    return normalise(cross(axis, cardinal))


def open_book(points_a, points_b) -> tuple[Placement, Placement]:
    """Separate the partners and turn each to face the viewer.

    Both rotate a half turn about the same perpendicular, in the same sense —
    which, because they end up on opposite sides of the gap, presents the two
    binding faces towards each other's original position and so towards the
    camera once the pair is viewed along that perpendicular.
    """
    centre_a, centre_b = centroid(points_a), centroid(points_b)
    axis = normalise(subtract(centre_b, centre_a))
    hinge = perpendicular(axis)
    span = max(_radius(points_a, centre_a), _radius(points_b, centre_b))
    gap = span * OPEN_BOOK_GAP
    return (
        Placement(hinge, 180.0, centre_a, tuple(-axis[i] * gap for i in range(3))),
        Placement(hinge, 0.0, centre_b, tuple(axis[i] * gap for i in range(3))),
    )


def _radius(points, centre: Vector) -> float:
    return max((norm(subtract(p, centre)) for p in points), default=0.0)


def rotate_about(v: Vector, axis: Vector, degrees: float) -> Vector:
    """Rodrigues rotation of `v` about a unit `axis`."""
    angle = math.radians(degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    axis = normalise(axis)
    dot = sum(axis[i] * v[i] for i in range(3))
    perp = cross(axis, v)
    return tuple(
        v[i] * cosine + perp[i] * sine + axis[i] * dot * (1 - cosine)
        for i in range(3)
    )


# Far enough that the camera starts outside the molecule; `view` moves it to
# fit immediately afterwards, so the exact value never reaches the figure.
SIDE_ON_DISTANCE = 150.0


def side_on(points_a, points_b, scene_points, roll: float = 0.0):
    """Camera basis and position looking *across* the interface axis.

    The third view, alongside face-on and open-book. Face-on looks down the
    axis joining the two interface centroids and answers "what shape is this
    contact"; this looks perpendicular to it, so the partners sit left and
    right with the contact patch as a vertical seam between them. It is the
    overview the published binder figures use, and it is the one that makes a
    multi-panel plate comparable, because every panel is then the same
    viewpoint rather than whatever the mouse was last left at.

    `roll` spins the camera about that axis. It is the only degree of freedom
    left once the axis is horizontal and there is no principled choice for it.

    Returns `(cam_x, cam_y, cam_z, origin)`. The first two are what any label
    offset has to be expressed in: an offset built from scene coordinates
    mostly points along `cam_z`, where it cannot be seen.
    """
    axis = interface_axis(points_a, points_b)
    centre = centroid(scene_points)
    toward_viewer = rotate_about(perpendicular(axis), axis, roll)
    cam_x = axis
    cam_z = normalise(toward_viewer)
    cam_y = cross(cam_z, cam_x)
    origin = tuple(centre[i] + cam_z[i] * SIDE_ON_DISTANCE for i in range(3))
    return cam_x, cam_y, cam_z, origin


def camera_matrix(cam_x: Vector, cam_y: Vector, cam_z: Vector, origin: Vector) -> str:
    """The 12 numbers `view matrix camera` wants, row-major.

    The matrix maps camera coordinates to scene coordinates, so its columns
    are the camera axes and its fourth column is the camera position.
    """
    rows = [(cam_x[i], cam_y[i], cam_z[i], origin[i]) for i in range(3)]
    return ",".join(f"{value:.5f}" for row in rows for value in row)


def fan_offsets(count: int, cam_x: Vector, cam_y: Vector, spread: float,
                start: int = 0, total: int | None = None):
    """`count` offsets spaced around a circle in the camera plane.

    `start` and `total` let two sides of an interface share one circle, so the
    labels of one partner do not land on the labels of the other.
    """
    total = total or count
    offsets = []
    for step in range(count):
        angle = 2 * math.pi * (start + step) / total
        dx, dy = math.cos(angle) * spread, math.sin(angle) * spread
        offsets.append(tuple(cam_x[i] * dx + cam_y[i] * dy for i in range(3)))
    return tuple(offsets)

def place_labels(points, angle_count, spread, start=0):
    """Choose a fan angle per point so the labels land clear of each other.

    `fan_offsets` spaces a set of labels evenly around a circle, which stops a
    residue's own label sitting on top of it and stops the two sides of an
    interface fanning into each other. What it cannot do is notice that two
    residues are close together on screen: their circles overlap, and two
    labels meet in the middle. On barnase-barstar that is exactly what happened
    to His102 and Tyr29, which printed over each other as one unreadable word.

    So the angle is chosen rather than assigned. Points are 2-D, already
    projected into the camera plane, and each label is placed at the candidate
    angle whose position is furthest from everything placed so far *and* from
    every residue being labelled -- a label that clears its neighbours' labels
    but lands on their side chains is no more readable.

    Ties keep the natural order, so a set of labels that has no collisions
    comes out exactly as `fan_offsets` would have drawn it.
    """
    import math

    chosen = []
    placed: list[tuple[float, float]] = []
    for index, (px, py) in enumerate(points):
        best_angle, best_score = None, None
        for step in range(angle_count):
            angle = 2 * math.pi * ((start + index + step) % angle_count) / angle_count
            lx, ly = px + math.cos(angle) * spread, py + math.sin(angle) * spread
            near_label = min(
                (math.hypot(lx - ox, ly - oy) for ox, oy in placed), default=float("inf")
            )
            near_residue = min(
                (math.hypot(lx - qx, ly - qy)
                 for other, (qx, qy) in enumerate(points) if other != index),
                default=float("inf"),
            )
            score = min(near_label, near_residue)
            # Strictly greater, so an equal score keeps the earlier candidate
            # and the natural angle wins a tie.
            if best_score is None or score > best_score:
                best_angle, best_score = angle, score
        chosen.append(best_angle)
        placed.append((px + math.cos(best_angle) * spread,
                       py + math.sin(best_angle) * spread))
    return tuple(chosen)


def offsets_at(angles, cam_x, cam_y, spread):
    """Camera-plane angles turned back into 3-D offset vectors."""
    import math

    return tuple(
        tuple(cam_x[i] * math.cos(angle) * spread + cam_y[i] * math.sin(angle) * spread
              for i in range(3))
        for angle in angles
    )


def project(point, cam_x, cam_y):
    """A 3-D point in the camera plane, as (u, v)."""
    return (sum(point[i] * cam_x[i] for i in range(3)),
            sum(point[i] * cam_y[i] for i in range(3)))
