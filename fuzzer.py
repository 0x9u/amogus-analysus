from __future__ import annotations

from typing import Optional
import random
from competency import Competency

from game import (
    Game,
    Player,
    PlayerState,
    Node,
    Action,
    NoneAction,
    MoveAction,
    StartTaskAction,
    WorkTaskAction,
    KillAction,
    ReportAction,
    SetStateAction,
    KILL_COOLDOWN_TICKS,
)

NO_IMPOSTERS = 2
GROUP_SIZE = NO_IMPOSTERS + 3 * NO_IMPOSTERS


class Fuzzer:
    def __init__(self, game: Game, seed: int | None = None, enable_competency: bool = True, group_size: int = GROUP_SIZE, debug: bool = False):
        if seed is not None:
            random.seed(seed)
        self.groups_initialised = False

        self.enable_competency = enable_competency
        self.group_size = group_size

        self._assign_competencies(game)

        self.debug = debug

    def ensure_groups(self, game: Game) -> None:
        if self.groups_initialised:
            return
        self.groups_initialised = True

        players = list(game.players)
        random.shuffle(players)

        groups = [players[i: i + self.group_size]
                  for i in range(0, len(players), self.group_size)]
        if self.debug:
            print(f"groups: {groups}")
        for group in groups:
            if not group:
                continue
            leader = random.choice(group)
            followers = [p for p in group if p is not leader]

            leader.player_following = followers
            leader.following_player = None
            leader.state = PlayerState.IDLE

            for f in followers:
                f.following_player = leader
                f.player_following = []
                f.state = PlayerState.FOLLOWING

            if self.debug:
                print(f"{leader} is group leader of {followers}")

    def _assign_competencies(self, game: Game) -> None:
        if not self.enable_competency:
            for p in game.players:
                p.competency = Competency.NORMAL
            return

        for p in game.players:
            if p.imposter:
                p.competency = Competency.NORMAL
            else:
                roll = random.random()
                if roll < 0.20:
                    p.competency = Competency.FULL
                elif roll < 0.40:
                    p.competency = Competency.TROLL
                else:
                    p.competency = Competency.NORMAL

    def competency_of(self, player: Player) -> Competency:
        if not self.enable_competency:
            return Competency.NORMAL
        return player.competency or Competency.NORMAL

    def reroll_group_leader(self, player: Player, include_self: bool, game: Game) -> None:
        other_followers = player.player_following
        if not other_followers:
            return

        current_node = game.get_player_current_node(player)
        # p in current_node.player for the trolls
        alive_followers = [p for p in other_followers if p.state !=
                           PlayerState.DEAD and p in current_node.players]
        if include_self and player.state != PlayerState.DEAD:
            alive_followers = alive_followers + [player]

        if not alive_followers:
            return

        new_leader = random.choice(alive_followers)
        rest = [p for p in other_followers + [player]
                if p is not new_leader and p.state != PlayerState.DEAD]

        new_leader.player_following = rest
        new_leader.following_player = None
        new_leader.state = PlayerState.IDLE

        for p in rest:
            p.following_player = new_leader
            p.player_following = []
            p.state = PlayerState.FOLLOWING

        if self.debug:
            print(f"{new_leader} rerolled as new group leader of {rest}")

    def decide_state(self, player: Player, game: Game) -> Action:
        if not self.groups_initialised:
            self.ensure_groups(game)

        if player.state == PlayerState.DEAD:
            return NoneAction()

        match player.state:
            case PlayerState.IDLE:
                if len(player.tasks) > 0 or player.current_task is not None:
                    return SetStateAction(PlayerState.WORKING)
                return NoneAction()

            case PlayerState.WORKING:
                random_chance_if_imposter = random.randint(
                    1, 4) if player.imposter else 0
                if (len(player.tasks) == 0 and player.current_task is None) or (
                    random_chance_if_imposter == 1
                ):
                    return SetStateAction(PlayerState.IDLE)
                return NoneAction()

            case PlayerState.FOLLOWING:
                if player.following_player is None:
                    return SetStateAction(PlayerState.IDLE)
                elif player.following_player.state == PlayerState.DEAD:
                    self.reroll_group_leader(
                        player.following_player, True, game)
                    return NoneAction()
                return NoneAction()

            case PlayerState.FIX_SABOTAGE:
                return NoneAction()

            case _:
                return NoneAction()

    def decide_action(self, player: Player, game: Game) -> Action:
        if player.state == PlayerState.DEAD:
            return NoneAction()

        auto_report = self._decide_auto_report_dead_body(player, game)
        if not isinstance(auto_report, NoneAction):
            return auto_report

        kill_action = self._decide_kill(player, game)
        if not isinstance(kill_action, NoneAction):
            return kill_action

        match player.state:
            case PlayerState.WORKING:
                return self._decide_working_action(player, game)
            case PlayerState.FOLLOWING:
                return self._decide_following_action(player, game)
            case PlayerState.FIX_SABOTAGE:
                return NoneAction()
            case _:
                return NoneAction()

    def decide_movement(self, player: Player, game: Game) -> Action:
        if player.state == PlayerState.DEAD:
            return NoneAction()

        if player.state == PlayerState.FOLLOWING:
            return self._decide_following_movement(player, game)

        if player.state == PlayerState.IDLE:
            return self._decide_idle_movement(player, game)

        if player.state == PlayerState.WORKING:
            if player.current_task is not None:
                if player.current_task.location != player.current_location:
                    return self._decide_working_movement(player, game)

        return NoneAction()

    def _decide_idle_movement(self, player: Player, game: Game) -> Action:
        c = self.competency_of(player)

        if c == Competency.TROLL:
            edges = game.edges[player.current_location]
            dest = random.choice(list(edges.keys()))
            return MoveAction(dest=dest)

        if c == Competency.FULL:
            current = game.get_player_current_node(player)
            edges = game.edges[current.name]
            best = None
            best_weight = -1

            for node_name, is_vent_edge in edges.items():
                if is_vent_edge and (not player.imposter or player.vent_cooldown > 0):
                    continue

                dislike = player.dislike_visited_node.get(node_name, 0.0)
                weight = (1.0 - dislike)
                if weight > best_weight:
                    best_weight = weight
                    best = node_name

            if best is None:
                return NoneAction()
            return MoveAction(dest=best)

        dest = self._choose_random_destination(player, game)
        if dest is None:
            return NoneAction()
        return MoveAction(dest=dest)

    def _decide_working_movement(self, player: Player, game: Game) -> Action:
        dest = self._choose_random_destination(player, game)
        if dest is None:
            return NoneAction()
        return MoveAction(dest=dest)

    def _decide_following_movement(self, player: Player, game: Game) -> Action:
        c = self.competency_of(player)

        imposter_leave_chance = random.randint(1, 4) if player.imposter else 0

        if c == Competency.TROLL or imposter_leave_chance == 1:
            return SetStateAction(PlayerState.IDLE)

        leader = player.following_player
        if leader is None:
            return SetStateAction(PlayerState.IDLE)

        leader_node = game.get_player_current_node(leader)
        if leader_node is not game.get_player_current_node(player):
            return MoveAction(dest=leader_node.name)

        return NoneAction()

    def _decide_auto_report_dead_body(self, player: Player, game: Game) -> Action:
        if player.state == PlayerState.DEAD:
            return NoneAction()
        if player.imposter:
            return NoneAction()

        dead_bodies = game.get_dead_bodies_unreported()
        if not dead_bodies:
            return NoneAction()

        c = self.competency_of(player)

        if c == Competency.FULL:
            return ReportAction(dead_bodies=dead_bodies)

        if c == Competency.NORMAL:
            if random.random() < 0.70:
                return ReportAction(dead_bodies=dead_bodies)
            return NoneAction()

        if c == Competency.TROLL:
            return NoneAction()

        return NoneAction()

    def _decide_kill(self, player: Player, game: Game) -> Action:
        if player.state == PlayerState.DEAD:
            return NoneAction()
        if not player.imposter:
            return NoneAction()
        if player.kill_cooldown > 0:
            return NoneAction()

        kill_chance = random.randint(1, 4)
        if kill_chance != 1:
            return NoneAction()

        players_in_node = game.get_other_players_in_current_node(player)
        # imposters_in_node = [p for p in players_in_node if p.imposter]
        crewmates_in_node = [
            p for p in players_in_node if not p.imposter and p.state != PlayerState.DEAD
        ]

        if len(crewmates_in_node) == 0:
            return NoneAction()
        # if len(imposters_in_node) + 1 < len(crewmates_in_node):
        #    return NoneAction()

        target = random.choice(crewmates_in_node)
        other_crewmates = [
            p
            for p in game.get_other_players_in_current_node(player)
            if not p.imposter and p.state != PlayerState.DEAD and p is not target
        ]

        self_report = False
        self_report_witness: Player | None = None
        witness_reporter: Player | None = None

        self_report_chance = random.randint(1, 4)
        if self_report_chance == 1:
            self_report = True
            if other_crewmates:
                self_report_witness = random.choice(other_crewmates)

        if other_crewmates:
            witness_reporter = None
            if other_crewmates:
                chosen = random.choice(other_crewmates)
                c = self.competency_of(chosen)

                if c == Competency.FULL:
                    witness_reporter = chosen
                elif c == Competency.NORMAL:
                    if random.random() < 0.5:
                        witness_reporter = chosen
                # trolls never report

        return KillAction(
            target=target,
            self_report=self_report,
            self_report_witness=self_report_witness,
            witness_reporter=witness_reporter,
        )

    def _choose_random_destination(self, player: Player, game: Game) -> Optional[str]:
        current_node = game.get_player_current_node(player)
        edges = game.edges.get(current_node.name, {})

        dest_nodes: list[Node] = []
        weights: list[float] = []

        for node_name, is_vent_edge in edges.items():
            node = game.nodes[node_name]
            if is_vent_edge and (not player.imposter or player.vent_cooldown > 0):
                continue

            dislike = player.dislike_visited_node.get(node.name, 0.0)
            extra_vent_weight = (
                player.kill_cooldown / KILL_COOLDOWN_TICKS * int(node.vent)
                if KILL_COOLDOWN_TICKS > 0
                else 0.0
            )
            weight = (1.0 - dislike) + extra_vent_weight
            if weight <= 0:
                continue
            dest_nodes.append(node)
            weights.append(weight)

        if not dest_nodes:
            return None

        chosen_node = random.choices(dest_nodes, weights=weights)[-1]
        return chosen_node.name

    def _decide_working_action(self, player: Player, game: Game) -> Action:
        if player.current_task is None:
            if not player.tasks:
                return NoneAction()

            c = self.competency_of(player)

            # if c == Competency.TROLL:
            #    return NoneAction()

            if c == Competency.FULL:
                # full competency: prefer shortest tasks first
                chosen_task = min(player.tasks, key=lambda t: t.length.value)
            else:
                chosen_task = random.choice(player.tasks)

            return StartTaskAction(task=chosen_task)

        task = player.current_task
        if task.location == player.current_location:
            return WorkTaskAction()

        return NoneAction()

    def _decide_following_action(self, player: Player, game: Game) -> Action:
        c = self.competency_of(player)

        if c == Competency.TROLL:
            return SetStateAction(PlayerState.IDLE)

        leader = player.following_player
        leader_node = game.get_player_current_node(leader)

        if leader_node.vent and not (player.imposter and player.vent_cooldown == 0):
            if self.debug:
                print("emergency report")
            return ReportAction(dead_bodies=None, witnessed=leader)

        return NoneAction()

    def tick(self, game: Game) -> None:
        game.step(
            decide_state=self.decide_state,
            decide_move=self.decide_movement,
            decide_action=self.decide_action,
        )
