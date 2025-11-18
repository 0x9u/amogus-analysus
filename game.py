from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import NamedTuple, Self, DefaultDict
from enum import Enum, auto
from competency import Competency

import os

class TaskLength(Enum):
    SHORT = 1
    MEDIUM = 2
    LONG = 3


TASK_TO_TICKS = {
    TaskLength.SHORT: 1,
    TaskLength.MEDIUM: 2,
    TaskLength.LONG: 3,
}

DELTA_DISLIKE = 0.15
MAX_DISLIKE = 0.9

FOLLOW_TICKS = 10
KILL_COOLDOWN_TICKS = 5
VENT_COOLDOWN_TICKS = 5

SABOTAGE_LOCATION_COOLDOWN_TICKS = 10
SABOTAGE_LIGHTS_COOLDOWN_TICKS = 10
SABOTAGE_DOOR_COOLDOWN_TICKS = 10

SUS_WINDOW = 2


class PlayerState(Enum):
    IDLE = auto()
    WORKING = auto()
    FOLLOWING = auto()
    DEAD = auto()
    FIX_SABOTAGE = auto()

    def __str__(self) -> str:
        return self.name


class Task(NamedTuple):
    name: str
    length: TaskLength
    visual: bool
    location: str
    next_task: list[str] | None


class SabotageVariant(Enum):
    DEADLY = auto()
    COMMS = auto()


class Sabotage(NamedTuple):
    name: str
    location: str
    variant: SabotageVariant


@dataclass
class Player:
    name: str
    imposter: bool
    tasks: list[Task]
    state: PlayerState
    current_location: str
    competency: Competency | None = None

    current_task: Task | None = None
    ticks_elapsed: int = 0
    dislike_visited_node: DefaultDict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    following_player: Self | None = None
    player_following: list[Self] = field(default_factory=list)
    vouch_history: set[Self] = field(default_factory=set)
    kill_cooldown: int = 0
    vent_cooldown: int = 0

    voted_out: bool = False
    dead_body_reported: bool = False

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return self.name


@dataclass
class Node:
    name: str
    players: list[Player]
    vent: bool

class ActionType(Enum):
    NONE = auto()
    MOVE = auto()
    START_TASK = auto()
    WORK_TASK_TICK = auto()
    KILL = auto()
    REPORT = auto()
    SET_STATE = auto()
    FOLLOW = auto()


@dataclass
class NoneAction:
    type: ActionType = ActionType.NONE


@dataclass
class MoveAction:
    dest: str
    type: ActionType = ActionType.MOVE


@dataclass
class StartTaskAction:
    task: Task
    type: ActionType = ActionType.START_TASK


@dataclass
class WorkTaskAction:
    type: ActionType = ActionType.WORK_TASK_TICK


@dataclass
class KillAction:
    target: Player
    self_report: bool = False
    self_report_witness: Player | None = None
    witness_reporter: Player | None = None
    type: ActionType = ActionType.KILL


@dataclass
class ReportAction:
    dead_bodies: list[Player] | None
    witnessed: Player | None = None
    type: ActionType = ActionType.REPORT


@dataclass
class SetStateAction:
    new_state: PlayerState
    type: ActionType = ActionType.SET_STATE


@dataclass
class FollowAction:
    leader: Player | None
    type: ActionType = ActionType.FOLLOW


Action = (
    NoneAction
    | MoveAction
    | StartTaskAction
    | WorkTaskAction
    | KillAction
    | ReportAction
    | SetStateAction
    | FollowAction # unused, will be used in testing for future
)


@dataclass
class MovementHistory:
    tick: int
    witness: Player
    subject: Player
    previous: str
    location: str


@dataclass
class KillWitnessHistory:
    tick: int
    killer: Player
    victim: Player
    witnesses: list[Player]

class Game:
    nodes: dict[str, Node]
    edges: DefaultDict[str, dict[str, bool]]
    tasks: dict[str, Task]
    sabotages: list[Sabotage]
    lights_sabotaged: bool
    current_sabotages: list[Sabotage]
    sabotage_cooldown: dict[str, int]

    players: list[Player]
    movement_history: list[MovementHistory]
    kill_witness_history: list[KillWitnessHistory]
    tick_counter: int
    action_history: list[tuple[int, Player, Action | str]]

    debug: bool

    def __init__(self, file: str, debug: bool = False):
        start: str | None = None
        self.nodes = {}
        self.edges = defaultdict(dict)
        self.tasks = {}
        self.sabotages = []
        self.lights_sabotaged = False
        self.current_sabotages = []
        self.sabotage_cooldown = {}
        self.players = []
        self.movement_history = []
        self.kill_witness_history = []
        self.tick_counter = 0
        self.action_history = []

        self.debug = debug

        node_names: set[str] = set()

        with open(file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                space_parts = line.split(" ")
                edge_parts = line.split("--")
                vent_edge_parts = line.split("-v-")
                task_parts = line.split("-t-")
                sabotage_parts = line.split("-s-")
                player_parts = line.split("-p-")

                if line.strip().startswith("//"):
                    continue

                if len(space_parts) == 2 and space_parts[0] == "start":
                    start = space_parts[1].strip()

                elif len(edge_parts) == 2:
                    a, b = edge_parts[0].strip(), edge_parts[1].strip()
                    node_names.add(a)
                    node_names.add(b)
                    self.edges[a][b] = False
                    self.edges[b][a] = False

                elif len(vent_edge_parts) == 2:
                    a, b = vent_edge_parts[0].strip(
                    ), vent_edge_parts[1].strip()
                    node_names.add(a)
                    node_names.add(b)
                    self.edges[a][b] = True
                    self.edges[b][a] = True

                elif len(task_parts) >= 3:
                    task_parts = list(map(lambda p: p.strip(), task_parts))
                    name, node, time, *optionals = task_parts

                    if time == "S":
                        length = TaskLength.SHORT
                    elif time == "M":
                        length = TaskLength.MEDIUM
                    elif time == "L":
                        length = TaskLength.LONG
                    else:
                        raise ValueError(f"unknown time {time}")

                    following_tasks = list(
                        filter(lambda p: p.startswith("->"), optionals))
                    if len(following_tasks) > 1:
                        raise ValueError(
                            f"too many following tasks {following_tasks}")
                    if following_tasks:
                        following_tasks = list(
                            map(
                                lambda p: p.strip(),
                                following_tasks[0].replace(
                                    "->", "").split(","),
                            )
                        )
                    else:
                        following_tasks = None

                    visual = list(filter(lambda p: p == "V", optionals))

                    self.tasks[name] = Task(
                        name=name,
                        length=length,
                        visual=len(visual) > 0,
                        location=node,
                        next_task=following_tasks,
                    )

                elif len(sabotage_parts) == 3:
                    sabotage_parts = list(
                        map(lambda p: p.strip(), sabotage_parts))
                    name, node, variant_str = sabotage_parts
                    if variant_str == "D":
                        variant = SabotageVariant.DEADLY
                    elif variant_str == "C":
                        variant = SabotageVariant.COMMS
                    else:
                        raise ValueError(f"unknown variant {variant_str}")

                    self.sabotages.append(Sabotage(name, node, variant))

                elif len(player_parts) >= 1:
                    player_parts = list(map(lambda p: p.strip(), player_parts))
                    name, *optionals = player_parts
                    imposter = "P" in optionals
                    tasks = list(
                        filter(lambda t: t.startswith("->"), optionals))
                    if len(tasks) > 1:
                        raise ValueError(f"too many tasks: {tasks}")
                    if tasks:
                        tasks = list(
                            map(
                                lambda p: self.tasks[p.strip()],
                                tasks[0].replace("->", "").split(","),
                            )
                        )
                    else:
                        tasks = []

                    self.players.append(
                        Player(name, imposter, tasks, PlayerState.IDLE, ""))

                else:
                    raise ValueError(f"unknown line {line} ({edge_parts})")

        if not start:
            raise ValueError("no starting node")

        for node_name in node_names:
            self.nodes[node_name] = Node(
                node_name,
                players=[],
                vent=node_name.find("vent") != -1,
            )

        # place all players into the start node
        start_node = self.nodes[start]
        for p in self.players:
            p.current_location = start_node.name
            start_node.players.append(p)
    def get_player_current_node(self, player: Player) -> Node:
        return self.nodes[player.current_location]

    def get_other_players_in_current_node(self, player: Player) -> list[Player]:
        node = self.get_player_current_node(player)
        return [p for p in node.players if p is not player]

    def get_dead_bodies_unreported(self) -> list[Player]:
        return [
            p
            for p in self.players
            if p.state == PlayerState.DEAD
            and not p.voted_out
            and not p.dead_body_reported
        ]

    def tick_cooldowns(self) -> None:
        for p in self.players:
            if p.state == PlayerState.DEAD:
                continue
            p.kill_cooldown = max(p.kill_cooldown - 1, 0)
            p.vent_cooldown = max(p.vent_cooldown - 1, 0)

    def step(
        self,
        decide_state,
        decide_move,
        decide_action,
    ) -> None:
        
        self.tick_counter += 1
        self.tick_cooldowns()

        for p in self.players:
            action = decide_state(p, self)
            self.apply_action(p, action)

        self.players.sort(key=lambda p: p.state == PlayerState.FOLLOWING)
        if self.debug: print(f"order of players: {self.players}")

        for p in self.players:
            action = decide_move(p, self)
            self.apply_action(p, action)

        for p in self.players:
            action = decide_action(p, self)
            self.apply_action(p, action)
    
    def check_crewmate_win(self) -> bool:
        imposters = [p for p in self.players if p.imposter]
        return all(p.state == PlayerState.DEAD for p in imposters)

    def check_imposter_win(self) -> bool:
        crewmates = [p for p in self.players if not p.imposter]
        return all(p.state == PlayerState.DEAD for p in crewmates)
    
    def apply_action(self, player: Player, action: Action) -> None:
        if isinstance(action, NoneAction):
            return

        self.action_history.append((self.tick_counter, player, action))

        if isinstance(action, SetStateAction):
            self._apply_set_state(player, action.new_state)
        elif isinstance(action, MoveAction):
            self._apply_move(player, action.dest)
        elif isinstance(action, StartTaskAction):
            self._apply_start_task(player, action.task)
        elif isinstance(action, WorkTaskAction):
            self._apply_work_task_tick(player)
        elif isinstance(action, KillAction):
            self._apply_kill(player, action)
        elif isinstance(action, ReportAction):
            self._apply_report(player, action)
        elif isinstance(action, FollowAction):
            self._apply_follow(player, action.leader)

    def _apply_set_state(self, player: Player, new_state: PlayerState) -> None:
        if player.state == PlayerState.DEAD:
            return
        player.state = new_state

    def _apply_move(self, player: Player, dest_name: str) -> None:
        if player.state == PlayerState.DEAD:
            return

        if dest_name not in self.nodes:
            return

        src_node = self.get_player_current_node(player)
        edges_from_src = self.edges.get(src_node.name, {})

        if dest_name not in edges_from_src:
            return

        is_vent = edges_from_src[dest_name]
        dest_node = self.nodes[dest_name]

        if is_vent and (not player.imposter or player.vent_cooldown > 0):
            return

        dislike = player.dislike_visited_node.get(dest_node.name, 0.0)
        player.dislike_visited_node[dest_node.name] = min(
            dislike + DELTA_DISLIKE, MAX_DISLIKE
        )

        if player in src_node.players:
            src_node.players.remove(player)
        if player not in dest_node.players:
            dest_node.players.append(player)
        player.current_location = dest_node.name

        for witness in dest_node.players:
            if witness is not player and witness.state != PlayerState.DEAD:
                # todo: apply competency to this
                self.movement_history.append(MovementHistory(
                    self.tick_counter, player, witness, src_node.name, dest_node.name))

        if src_node.vent and not dest_node.vent:
            player.vent_cooldown = VENT_COOLDOWN_TICKS

    def _apply_start_task(self, player: Player, task: Task) -> None:
        if player.state == PlayerState.DEAD:
            return

        if task not in player.tasks and player.current_task is not None:
            return

        player.current_task = task
        if not player.imposter and task in player.tasks:
            player.tasks.remove(task)

    def _apply_work_task_tick(self, player: Player) -> None:
        if player.state == PlayerState.DEAD:
            return
        if player.current_task is None:
            return

        task = player.current_task

        if task.location != player.current_location:
            return

        player.ticks_elapsed += 1
        if player.ticks_elapsed < TASK_TO_TICKS[task.length]:
            return

        player.ticks_elapsed = 0
        
        if task.next_task is not None and not player.imposter:
            next_name = task.next_task[0]
            if next_name in self.tasks:
                next_task = self.tasks[next_name]
                player.tasks.append(next_task)

        if task.visual and not player.imposter:
            for follower in player.player_following:
                follower.vouch_history.add(player)

        player.current_task = None

    def _apply_kill(self, attacker: Player, action: KillAction) -> None:
        if attacker.state == PlayerState.DEAD:
            return
        if not attacker.imposter:
            return
        if attacker.kill_cooldown > 0:
            return

        target = action.target
        if target.state == PlayerState.DEAD:
            return
        if target.imposter:
            return

        if self.get_player_current_node(attacker) is not self.get_player_current_node(
            target
        ):
            return

        node = self.get_player_current_node(attacker)
        witnesses = [
            p for p in node.players
            if p not in (attacker, target)
            and p.state != PlayerState.DEAD
        ]

        self.kill_witness_history.append(
            KillWitnessHistory(self.tick_counter, attacker, target, witnesses)
        )

        target.state = PlayerState.DEAD
        if self.debug: print(f"{attacker} killed {target}")

        if target in attacker.player_following:
            attacker.player_following.remove(target)
            target.following_player = None

        if attacker.following_player is target:
            attacker.following_player = None

        attacker.kill_cooldown = KILL_COOLDOWN_TICKS

        if action.self_report:
            if self.debug: print(f"self report by {attacker} for {target}")
            self.report(
                reporter=attacker,
                dead_bodies=[target],
                witnessed=action.self_report_witness,
            )

        if action.witness_reporter is not None:
            if self.debug: print(
                f"{target} witnessed {attacker} kill (reported by {action.witness_reporter})"
            )
            self.report(
                reporter=action.witness_reporter,
                dead_bodies=[target],
                witnessed=attacker,
            )

    def _apply_report(self, reporter: Player, action: ReportAction) -> None:
        if reporter.state == PlayerState.DEAD:
            return
        self.report(reporter, action.dead_bodies, action.witnessed)

    # unused, will be used in testing for future
    def _apply_follow(self, player: Player, leader: Player | None) -> None:
        if player.state == PlayerState.DEAD:
            return

        if player.following_player is not None:
            old_leader = player.following_player
            if player in old_leader.player_following:
                old_leader.player_following.remove(player)
            player.following_player = None

        if leader is None:
            player.state = PlayerState.IDLE
            return

        player.following_player = leader
        if player not in leader.player_following:
            leader.player_following.append(player)
        player.state = PlayerState.FOLLOWING

    def report(
        self,
        reporter: Player,
        dead_bodies: list[Player] | None,
        witnessed: Player | None = None,
    ) -> None:
        if dead_bodies:
            for p in dead_bodies:
                p.dead_body_reported = True

        if witnessed:
            # todo: maybe use history instead for this?
            imposters_in_node = [
                p
                for p in self.get_other_players_in_current_node(reporter)
                if p.imposter and p.state != PlayerState.DEAD
            ]
            crewmates_in_node = [
                p
                for p in self.get_other_players_in_current_node(reporter)
                if not p.imposter and p.state != PlayerState.DEAD
            ]

            if reporter.imposter:
                imposters_in_node.append(reporter)
            else:
                crewmates_in_node.append(reporter)

            if self.debug: print(
                f"witness diff: {len(imposters_in_node) - len(crewmates_in_node)} {imposters_in_node=} {crewmates_in_node=}")

            if len(imposters_in_node) - len(crewmates_in_node) >= 1:
                if self.debug: print("voted out reporter")
                reporter.state = PlayerState.DEAD
                reporter.voted_out = True
                self._log_report_outcome(reporter, witnessed, dead_bodies, reporter)
                return
            elif len(crewmates_in_node) - len(imposters_in_node) >= 1:
                if self.debug: print("voted out witnessed player")
                if reporter.imposter:
                    # in this case, its obvious that the crewmates would vote out the fake reporter
                    reporter.state = PlayerState.DEAD
                    reporter.voted_out = True
                    self._log_report_outcome(reporter, witnessed, dead_bodies, reporter)
                else:
                    witnessed.state = PlayerState.DEAD
                    witnessed.voted_out = True
                    self._log_report_outcome(reporter, witnessed, dead_bodies, witnessed)
                return
            else:
                if self.debug: print("not enough majority information")
                return

        dead_set = set(dead_bodies or [])

        # find earliest witness entry
        relevant = [
            entry for entry in self.kill_witness_history
            if entry.victim in dead_set
        ]

        latest_entry = relevant[0]

        witnesses = latest_entry.witnesses
        kill_tick = latest_entry.tick
        if witnesses:
            if self.debug: print(f"direct witnesses: {witnesses}")
            latest_entry.killer.state = PlayerState.DEAD
            latest_entry.killer.voted_out = True
            self._log_report_outcome(reporter, latest_entry.killer, dead_bodies, latest_entry.killer)
            return

        sus_score = {p: 0 for p in self.players if p.state != PlayerState.DEAD}

        kill_node = self.get_player_current_node(latest_entry.killer)
        for p in kill_node.players:
            if p not in dead_set and p.state != PlayerState.DEAD:
                sus_score[p] += 1

        # players who recently witnesses someone moving to kill node
        for entry in self.movement_history:
            if entry.subject.state == PlayerState.DEAD or entry.witness.state == PlayerState.DEAD:
                continue
            if (entry.tick - kill_tick <= 2 and entry.previous == kill_node.name) or \
                    (kill_tick - entry.tick < 2 and entry.location == kill_node.name):
                sus_score[entry.subject] += 1

        for p in self.players:
            if p.state == PlayerState.DEAD:
                continue
            
            if set(p.player_following) & dead_set:
                sus_score[p] += 1
            elif p.following_player in dead_set:
                sus_score[p] += 1

        for p in self.players:
            for s in sus_score.keys():
                if s in p.vouch_history and p.state != PlayerState.DEAD:
                    sus_score[s] = 0

        if self.debug: print(f"reporter: {reporter}")

        max_sus = max(sus_score.values())
        possible_suspects = [
            p for p in sus_score.keys() if p.state != PlayerState.DEAD and max_sus - SUS_WINDOW <= sus_score[p] <= max_sus]
        if self.debug: print(f"possible suspects: {possible_suspects}")

        is_suspects_all_in_same_group = True
        for p in possible_suspects:
            others = [s for s in possible_suspects if s is not p]
            if not (
                all(s.following_player is p for s in others)
                or set(others) == set(p.player_following)
            ):
                is_suspects_all_in_same_group = False
                break

        if (
            (len(possible_suspects) != 1 and not is_suspects_all_in_same_group)
            or len(possible_suspects) == 0
        ):
            if self.debug: print(f"not enough information: {possible_suspects}")
            self._log_report_outcome(reporter, witnessed, dead_bodies, None)
            return

        chosen = possible_suspects[0]
        chosen.state = PlayerState.DEAD
        chosen.voted_out = True
        if self.debug: print(f"voted out {chosen}")
        self._log_report_outcome(reporter, witnessed, dead_bodies, chosen)

    # MISC
    def _log_report_outcome(self, reporter: Player, witnessed: Player | None, dead_bodies: list[Player], voted_out: Player | None) -> None:
        self.action_history.append(
            (
                self.tick_counter,
                reporter,
                f"REPORT_OUTCOME: {reporter=}, {witnessed=}, {dead_bodies=}, {voted_out=}",
            ))

    def get_actions_per_tick(self) -> dict[int, list[tuple[Player, Action | str]]]:
        result: dict[int, list[tuple[Player, Action | str]]] = {}
        for tick, player, action in self.action_history:
            if tick not in result:
                result[tick] = []
            result[tick].append((player, action))
        return result

    def print_action_history(self, filename: str) -> None:
        actions = self.get_actions_per_tick()
        actionDir = "actions"
        os.makedirs(actionDir, exist_ok=True)

        with open(os.path.join(actionDir, f"{filename}.csv"), "w") as f:
            f.write(f"tick,player,action\n")
            for tick in sorted(actions.keys()):
                for player, action in actions[tick]:
                    f.write(f"{tick},{player.name},{action}\n")
