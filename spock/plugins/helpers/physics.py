"""
PhysicsPlugin is planned to provide vectors and tracking necessary to implement
SMP-compliant client-side physics for entities. Primarirly this will be used to
keep update client position for gravity/knockback/water-flow etc. But it should
also eventually provide functions to track other entities affected by SMP
physics

Minecraft client/player physics is unfortunately very poorly documented.
Most of these values are based of experimental results and the contributions of
a handful of people (Thank you 0pteron!) to the Minecraft wiki talk page on
Entities and Transportation. Ideally someone will decompile the client with MCP
and document the totally correct values and behaviors.
"""

import collections
import logging
import math

from spock.mcdata import constants as const
from spock.mcmap import mapdata
from spock.plugins.base import PluginBase
from spock.utils import BoundingBox, pl_announce
from spock.vector import Vector3

logger = logging.getLogger('spock')

FP_MAGIC = 1e-4


class PhysicsCore(object):
    def __init__(self, vec, pos, bounding_box):
        self.vec = vec
        self.pos = pos
        self.bounding_box = bounding_box

    def jump(self):
        if self.pos.on_ground:
            self.vec += Vector3(0, const.PLAYER_JMP_ACC, 0)

    def walk(self, angle, radians=False):
        angle = angle if radians else math.radians(angle)
        z = math.cos(angle) * const.PLAYER_WLK_ACC
        x = math.sin(angle) * const.PLAYER_WLK_ACC
        self.vec += Vector3(x, 0, z)

    def sprint(self, angle, radians=False):
        angle = angle if radians else math.radians(angle)
        z = math.cos(angle) * const.PLAYER_SPR_ACC
        x = math.sin(angle) * const.PLAYER_SPR_ACC
        self.vec += Vector3(x, 0, z)


@pl_announce('Physics')
class PhysicsPlugin(PluginBase):
    requires = ('Event', 'ClientInfo', 'World')
    events = {
        'physics_tick': 'tick',
        'cl_position_update': 'clear_velocity',
    }
    unit_vectors = Vector3(1, 0, 0), Vector3(0, 1, 0), Vector3(0, 0, 1)

    def __init__(self, ploader, settings):
        super(PhysicsPlugin, self).__init__(ploader, settings)
        self.vec = Vector3(0.0, 0.0, 0.0)
        self.bounding_box = BoundingBox(0.6, 1.8)
        self.pos = self.clientinfo.position
        ploader.provides(
            'Physics', PhysicsCore(self.vec, self.pos, self.bounding_box)
        )

    def tick(self, _, __):
        self.vec -= Vector3(0, const.PLAYER_ENTITY_GAV, 0)
        self.vec -= self.get_drag(self.vec)
        mtv = self.get_mtv()
        self.pos.on_ground = mtv.y > 0
        self.apply_vector(mtv)

    def clear_velocity(self, _=None, __=None):
        self.vec.__init__(0, 0, 0)

    def get_drag(self, vec):
        vert = Vector3(0, vec.y, 0) * const.PLAYER_ENTITY_DRG
        horz = Vector3(vec.x, 0, vec.z) * const.PLAYER_GND_DRG
        return vert + horz

    def apply_vector(self, mtv):
        self.pos += (self.vec + mtv)
        self.vec.x = 0 if mtv.x else self.vec.x
        self.vec.y = 0 if mtv.y else self.vec.y
        self.vec.z = 0 if mtv.z else self.vec.z

    def gen_block_set(self, block_pos):
        offsets = (
            (x, y, z)
            for x in (-1, 0, 1) for y in (0, 1, 2) for z in (-1, 0, 1)
        )
        return (block_pos + Vector3(*offset) for offset in offsets)

    def check_collision(self, pos, vector):
        test_pos = pos + vector
        return self.block_collision(test_pos.floor(), test_pos)

    # Breadth-first search for a minimum translation vector
    def get_mtv(self):
        pos = self.pos + self.vec
        pos.x -= self.bounding_box.w/2
        pos.z -= self.bounding_box.d/2
        transform_vectors = []
        q = collections.deque()
        while q or not transform_vectors:
            current_vector = q.popleft() if q else Vector3()
            transform_vectors = self.check_collision(pos, current_vector)
            if not all(transform_vectors):
                break
            for vector in transform_vectors:
                test_vec = self.vec + current_vector + vector
                if test_vec.dist_sq() <= self.vec.dist_sq() + FP_MAGIC:
                    q.append(current_vector + vector)
        else:
            logger.warn('Physics failed to generate an MTV, bailing out')
            self.clear_velocity()
            return Vector3()
        possible_mtv = [current_vector]
        while q:
            current_vector = q.popleft()
            transform_vectors = self.check_collision(pos, current_vector)
            if not all(transform_vectors):
                possible_mtv.append(current_vector)
        return min(possible_mtv)

    def block_collision(self, center_block_pos, pos):
        for block_pos in self.gen_block_set(center_block_pos):
            block_id, meta = self.world.get_block(
                block_pos.x, block_pos.y, block_pos.z
            )
            block = mapdata.get_block(block_id, meta)
            if not block.bounding_box:
                continue
            transform_vectors = []
            for i, axis in enumerate(self.unit_vectors):
                axis_pen = self.check_axis(
                    axis, pos[i], pos[i] + self.bounding_box[i],
                    block_pos[i], block_pos[i] + block.bounding_box[i]
                )
                if not axis_pen:
                    break
                transform_vectors.append(axis_pen)
            else:
                return transform_vectors
        return [Vector3()]*3

    # Axis must be a normalized/unit vector
    def check_axis(self, axis, min_a, max_a, min_b, max_b):
        l_dif = (max_b - min_a)
        r_dif = (max_a - min_b)
        if l_dif < 0 or r_dif < 0:
            return None
        overlap = l_dif if l_dif <= r_dif else -r_dif
        return axis*overlap
