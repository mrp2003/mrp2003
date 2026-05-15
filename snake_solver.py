"""Port of Platane/snk's snake-pathfinding solver.

Source: https://github.com/Platane/snk/tree/main/packages/solver

Strategy: clear the grid one color (intensity level) at a time, ascending.
For each color, find cells reachable via a "tunnel" (snake enters from outside,
eats target, exits to outside) and walk the snake through each tunnel in turn.
For colors > 1, a residual pass picks up any cells of lower colors that were
walled off during their own pass.
"""

import heapq
import itertools
from collections import deque


AROUND4 = ((1, 0), (0, -1), (-1, 0), (0, 1))


class Grid:
    __slots__ = ("width", "height", "data")

    def __init__(self, width, height, data=None):
        self.width = width
        self.height = height
        self.data = bytearray(data) if data is not None else bytearray(width * height)

    def copy(self):
        return Grid(self.width, self.height, self.data)


def _idx(g, x, y):
    return x * g.height + y


def is_inside(g, x, y):
    return 0 <= x < g.width and 0 <= y < g.height


def is_inside_large(g, m, x, y):
    return -m <= x < g.width + m and -m <= y < g.height + m


def get_color(g, x, y):
    return g.data[_idx(g, x, y)]


def get_color_safe(g, x, y):
    return get_color(g, x, y) if is_inside(g, x, y) else 0


def set_color(g, x, y, c):
    g.data[_idx(g, x, y)] = c


def set_empty_safe(g, x, y):
    if is_inside(g, x, y):
        g.data[_idx(g, x, y)] = 0


def is_empty_safe(g, x, y):
    return not is_inside(g, x, y) or get_color(g, x, y) == 0


def make_snake(cells):
    b = bytearray(len(cells) * 2)
    for i, (x, y) in enumerate(cells):
        b[i * 2] = x + 2
        b[i * 2 + 1] = y + 2
    return bytes(b)


def snake_head_x(s):
    return s[0] - 2


def snake_head_y(s):
    return s[1] - 2


def snake_length(s):
    return len(s) // 2


def next_snake(s, dx, dy):
    nb = bytearray(len(s))
    nb[2:] = s[:-2]
    nb[0] = s[0] + dx
    nb[1] = s[1] + dy
    return bytes(nb)


def snake_will_self_collide(s, dx, dy):
    nx = s[0] + dx
    ny = s[1] + dy
    for i in range(2, len(s) - 2, 2):
        if s[i] == nx and s[i + 1] == ny:
            return True
    return False


class Outside:
    __slots__ = ("grid",)

    def __init__(self, grid):
        self.grid = grid


def is_outside(out, x, y):
    return not is_inside(out.grid, x, y) or get_color(out.grid, x, y) == 0


def fill_outside(out, g, color=0):
    og = out.grid
    changed = True
    while changed:
        changed = False
        for x in range(og.width - 1, -1, -1):
            for y in range(og.height - 1, -1, -1):
                if (
                    get_color(g, x, y) <= color
                    and not is_outside(out, x, y)
                    and any(is_outside(out, x + dx, y + dy) for dx, dy in AROUND4)
                ):
                    changed = True
                    og.data[_idx(og, x, y)] = 0


def create_outside(g, color=0):
    og = Grid(g.width, g.height)
    for i in range(len(og.data)):
        og.data[i] = 1
    out = Outside(og)
    fill_outside(out, g, color)
    return out


def get_tunnel_path(snake0, tunnel):
    chain = []
    s = snake0
    for i in range(1, len(tunnel)):
        dx = tunnel[i][0] - snake_head_x(s)
        dy = tunnel[i][1] - snake_head_y(s)
        s = next_snake(s, dx, dy)
        chain.insert(0, s)
    return chain


def trim_tunnel_start(g, tunnel):
    while tunnel and is_empty_safe(g, tunnel[0][0], tunnel[0][1]):
        tunnel.pop(0)


def trim_tunnel_end(g, tunnel):
    while tunnel:
        i = len(tunnel) - 1
        x, y = tunnel[i]
        first = -1
        for j in range(len(tunnel)):
            if tunnel[j][0] == x and tunnel[j][1] == y:
                first = j
                break
        if is_empty_safe(g, x, y) or first < i:
            tunnel.pop()
        else:
            break


class _Node:
    __slots__ = ("snake", "parent", "w")

    def __init__(self, snake, parent, w):
        self.snake = snake
        self.parent = parent
        self.w = w


def _unwrap_head_path(node):
    path = []
    while node is not None:
        path.append((snake_head_x(node.snake), snake_head_y(node.snake)))
        node = node.parent
    path.reverse()
    return path


def _snake_escape_path(g, out, snake0, color):
    counter = itertools.count()
    start = _Node(snake0, None, 0)
    open_list = [(0, next(counter), start)]
    closed = {snake0}
    while open_list:
        _, _, o = heapq.heappop(open_list)
        x, y = snake_head_x(o.snake), snake_head_y(o.snake)
        if is_outside(out, x, y):
            return _unwrap_head_path(o)
        for dx, dy in AROUND4:
            c = get_color_safe(g, x + dx, y + dy)
            if c <= color and not snake_will_self_collide(o.snake, dx, dy):
                ns = next_snake(o.snake, dx, dy)
                if ns not in closed:
                    closed.add(ns)
                    w = o.w + 1 + (1000 if c == color else 0)
                    heapq.heappush(open_list, (w, next(counter), _Node(ns, o, w)))
    return None


def get_best_tunnel(g, out, x, y, color, snake_n):
    snake0 = make_snake([(x, y)] * snake_n)
    one = _snake_escape_path(g, out, snake0, color)
    if one is None:
        return None
    snake_i_cells = list(one[:snake_n])
    while len(snake_i_cells) < snake_n:
        snake_i_cells.append(snake_i_cells[-1])
    snake_i = make_snake(snake_i_cells)
    gi = g.copy()
    for px, py in one:
        set_empty_safe(gi, px, py)
    two = _snake_escape_path(gi, out, snake_i, color)
    if two is None:
        return None
    result = list(reversed(one[1:])) + two
    trim_tunnel_start(g, result)
    trim_tunnel_end(g, result)
    return result


def get_path_to(g, snake0, tx, ty):
    counter = itertools.count()
    start = {"snake": snake0, "parent": None, "w": 0, "f": 0}
    open_list = [(0, next(counter), start)]
    closed = {snake0}
    while open_list:
        _, _, c = heapq.heappop(open_list)
        cx, cy = snake_head_x(c["snake"]), snake_head_y(c["snake"])
        for dx, dy in AROUND4:
            nx, ny = cx + dx, cy + dy
            if nx == tx and ny == ty:
                end_snake = next_snake(c["snake"], dx, dy)
                path = [end_snake]
                e = c
                while e["parent"] is not None:
                    path.append(e["snake"])
                    e = e["parent"]
                return path
            if (
                is_inside_large(g, 2, nx, ny)
                and not snake_will_self_collide(c["snake"], dx, dy)
                and is_empty_safe(g, nx, ny)
            ):
                ns = next_snake(c["snake"], dx, dy)
                if ns not in closed:
                    closed.add(ns)
                    w = c["w"] + 1
                    h = abs(nx - tx) + abs(ny - ty)
                    f = w + h
                    heapq.heappush(
                        open_list,
                        (f, next(counter), {"snake": ns, "parent": c, "w": w, "f": f}),
                    )
    return None


def _bfs_to_any_point(g, snake0, color, points):
    open_list = deque()
    open_list.append((snake0, None))
    closed = {snake0}
    while open_list:
        snake, parent = open_list.popleft()
        x, y = snake_head_x(snake), snake_head_y(snake)
        idx = -1
        for i in range(len(points)):
            if points[i][0] == x and points[i][1] == y:
                idx = i
                break
        if idx >= 0:
            points.pop(idx)
            out = []
            n = (snake, parent)
            while n is not None:
                out.append(n[0])
                n = n[1]
            return out
        for dx, dy in AROUND4:
            nx, ny = x + dx, y + dy
            if (
                is_inside_large(g, 2, nx, ny)
                and not snake_will_self_collide(snake, dx, dy)
                and get_color_safe(g, nx, ny) <= color
            ):
                ns = next_snake(snake, dx, dy)
                if ns not in closed:
                    closed.add(ns)
                    open_list.append((ns, (snake, parent)))
    return None


def _tunnellable_points_clean(g, out, snake_n, color):
    points = []
    seen = set()
    for x in range(g.width - 1, -1, -1):
        for y in range(g.height - 1, -1, -1):
            c = get_color(g, x, y)
            if c != 0 and c <= color and (x, y) not in seen:
                tunnel = get_best_tunnel(g, out, x, y, color, snake_n)
                if tunnel:
                    for px, py in tunnel:
                        if not is_empty_safe(g, px, py) and (px, py) not in seen:
                            points.append((px, py))
                            seen.add((px, py))
    return points


def clear_clean_colored_layer(g, out, snake0, color):
    snake_n = snake_length(snake0)
    points = _tunnellable_points_clean(g, out, snake_n, color)
    chain = [snake0]
    while points:
        path = _bfs_to_any_point(g, chain[0], color, points)
        if path is None:
            break
        path.pop()
        for s in path:
            set_empty_safe(g, snake_head_x(s), snake_head_y(s))
        chain[:0] = path
    fill_outside(out, g)
    chain.pop()
    return chain


def _tunnel_priority(g, color, tunnel):
    n_color = 0
    n_less = 0
    seen = set()
    for x, y in tunnel:
        if (x, y) in seen:
            continue
        seen.add((x, y))
        c = get_color_safe(g, x, y)
        if c != 0:
            if c == color:
                n_color += 1
            else:
                n_less += color - c
    if n_color == 0:
        return 99999
    return n_less / n_color


def _tunnellable_with_priority(g, out, snake_n, color):
    result = []
    for x in range(g.width - 1, -1, -1):
        for y in range(g.height - 1, -1, -1):
            c = get_color(g, x, y)
            if c != 0 and c < color:
                tunnel = get_best_tunnel(g, out, x, y, color, snake_n)
                if tunnel is not None:
                    result.append(
                        {
                            "x": x,
                            "y": y,
                            "tunnel": tunnel,
                            "priority": _tunnel_priority(g, color, tunnel),
                        }
                    )
    return result


def _pick_next_tunnel(ts, snake):
    top = ts[0]["priority"]
    hx, hy = snake_head_x(snake), snake_head_y(snake)
    best = None
    best_d = float("inf")
    for t in ts:
        if t["priority"] != top:
            break
        sx, sy = t["tunnel"][0]
        d = (sx - hx) ** 2 + (sy - hy) ** 2
        if d < best_d:
            best_d = d
            best = t["tunnel"]
    return best


def clear_residual_colored_layer(g, out, snake0, color):
    snake_n = snake_length(snake0)
    tunnels = _tunnellable_with_priority(g, out, snake_n, color)
    tunnels.sort(key=lambda t: -t["priority"])
    chain = [snake0]
    while tunnels:
        t = _pick_next_tunnel(tunnels, chain[0])
        if t is None:
            break
        p1 = get_path_to(g, chain[0], t[0][0], t[0][1])
        if p1 is None:
            break
        chain[:0] = p1
        p2 = get_tunnel_path(chain[0], t)
        chain[:0] = p2
        for tx, ty in t:
            set_empty_safe(g, tx, ty)
        fill_outside(out, g)
        next_tunnels = []
        for tt in tunnels:
            if get_color(g, tt["x"], tt["y"]) == 0:
                continue
            nt = get_best_tunnel(g, out, tt["x"], tt["y"], color, snake_n)
            if nt is None:
                continue
            tt["tunnel"] = nt
            tt["priority"] = _tunnel_priority(g, color, nt)
            next_tunnels.append(tt)
        next_tunnels.sort(key=lambda t: -t["priority"])
        tunnels = next_tunnels
    chain.pop()
    return chain


def get_best_route(grid, snake0):
    """Return a chain of snake states from snake0 (index 0) to the final state."""
    g = grid.copy()
    out = create_outside(g)
    chain = [snake0]
    max_color = max(g.data) if g.data else 0
    for color in range(1, max_color + 1):
        if color > 1:
            chain[:0] = clear_residual_colored_layer(g, out, chain[0], color)
        chain[:0] = clear_clean_colored_layer(g, out, chain[0], color)
    chain.reverse()
    return chain
