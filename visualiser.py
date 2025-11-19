#!/usr/bin/env python

from typing import NamedTuple

import pygame as pg

from game import  Game, PlayerState
from fuzzer import Fuzzer

FPS = 60
LINE_WIDTH = 2
NODE_SIZE = 20
PLAYER_BOX_WIDTH = 100
WIDTH, HEIGHT = 1000, 600

SIMULATE_SECONDS = 2

TIMER_EVENT = pg.USEREVENT + 1

SEED = 97
# seed 1, red imposter immediately kills cyan crewmate and gets voted out at tick 1
# seed 67, red imposter is followed and kills cyan crewmate and gets voted out at tick 2
# seed 65, red imposter leaves group at tick 2, red kills pink and self reports blaming white but gets voted out due to majority witnesses

# comms sabotaged -> put current task back into array if haven't found already, prevent working state
# reactor meltdown -> prioritise FIX_SABOTAGE (for now we won't emulate the countdown)
# door sabotage -> node is inaccessible for x ticks
# fix lights -> implement when we add meetings? crewmates cannot recall who was next to them, imposters dont give af if there are too many crewmates in one area to kill

# todo: dont bother making the imposter sneaky
# todo: everyone is in groups of 2

# todo: following should occur for crewmates that are working
# todo: self-arrange into groups of two
# todo: have a history of tasks visually done

# Assumption: total trust between partners in meeting if nothing diff happened between them

class GUINode(NamedTuple):
    name: str
    x: int
    y: int

class GUI:
    game : Game
    fuzzer: Fuzzer
    gui_nodes : list[GUINode]
    def __init__(self, game: Game, fuzzer: Fuzzer, display_path: str) -> None:
        pg.init()
        
        self.font = pg.font.SysFont("Arial", 20)
        self.tick_font = pg.font.SysFont("Arial", 48)
        self.screen = pg.display.set_mode((WIDTH, HEIGHT))
        pg.display.set_caption("Amogus Analysus")
        pg.display.set_icon(pg.image.load("icon.jpg"))
        
        self.game = game
        self.fuzzer = fuzzer
        
        self.read_display_info(display_path)
        
        assert set(map(lambda node: node.name, self.gui_nodes)) == set(game.nodes.keys()), "Name mismatch"
        
        self.render_surface = pg.Surface(self.bg.get_size())
        
        self.clock = pg.time.Clock()
        
        self.ticks = 0
    
    def read_display_info(self, display_path: str) -> None:
        self.gui_nodes = []
        with open(display_path, "r") as file:
            img_path = file.readline().replace("path", "").strip()
            
            self.bg = pg.image.load(img_path)
                
            for line in file:
                line = line.strip()
                if not line:
                    continue
                name, coords = line.split("|")
                x,y = coords.split(",")
                self.gui_nodes.append(GUINode(name.strip(), int(x), int(y)))


    def draw(self) -> None:
        self.render_surface.blit(self.bg, (0, 0))
        
        already_done_edges : set[tuple[str, str]] = set()
        
        for node, edges in self.game.edges.items():
            for other_node, vent in edges.items():
                if (node, other_node) in already_done_edges or (other_node, node) in already_done_edges:
                    continue
                
                start_node = next(filter(lambda n: n.name == node, self.gui_nodes))
                end_node = next(filter(lambda n: n.name == other_node, self.gui_nodes))
            
                already_done_edges.add((node, other_node))
                pg.draw.line(self.render_surface, pg.Color("black") if not vent else pg.Color("red"), (start_node.x + 10, start_node.y + 10), (end_node.x + 10, end_node.y + 10), LINE_WIDTH)
        
                
        for gui_node in self.gui_nodes:
            pg.draw.rect(self.render_surface, pg.Color("red"), (gui_node.x, gui_node.y, NODE_SIZE, NODE_SIZE))
            node_name_text_surface = self.font.render(gui_node.name, True, pg.Color("black"))
            self.render_surface.blit(node_name_text_surface, (gui_node.x, gui_node.y - 2 * NODE_SIZE))
        
        for gui_node in self.gui_nodes:
            information_coords = (gui_node.x + 2 * NODE_SIZE, gui_node.y)
            accum_y = 0
            max_x = PLAYER_BOX_WIDTH
            text_surfaces : list[tuple[pg.surface.Surface, tuple[int, int]]] = []
            node = self.game.nodes[gui_node.name]
            for player in node.players:
                player_information_coords = (information_coords[0], information_coords[1] + accum_y)
                
                state_text = f"{player.state} [{player.competency.name}]"
                
                image_gap = "     "
                if player.voted_out:
                    state_text += " - VOTED OUT"
                     
                text_surface = self.font.render(f"{image_gap} - {state_text} {image_gap if player.state == PlayerState.FOLLOWING and player.following_player is not None else ""} Current Task {player.current_task.name if player.current_task else 'None'}, Tasks: { ', '.join([task.name for task in player.tasks])}", True, pg.Color("black") if not player.imposter else pg.Color("red"))
                
                # insert crewmate images
                image = pg.image.load(f"players/{player.name}.png")
                image = pg.transform.scale(image, (20, 20))
                text_surface.blit(image, (0,0))
                
                if player.state == PlayerState.FOLLOWING and player.following_player is not None:
                    image = pg.image.load(f"players/{player.following_player.name}.png")
                    image = pg.transform.scale(image, (30, 30))
                    text_surface.blit(image, (230,0))
                
                text_surfaces.append((text_surface, player_information_coords))
                accum_y += text_surface.get_height()
                max_x = max(max_x, text_surface.get_width())
            
            pg.draw.rect(self.render_surface, pg.Color("white"), (information_coords[0], information_coords[1], max_x, accum_y))
            
            for text_surface, player_information_coords in text_surfaces:
                self.render_surface.blit(text_surface, player_information_coords)
        
        tick_text_surface = self.tick_font.render(f"Tick: {self.ticks}", True, pg.Color("black"))
        pg.draw.rect(self.render_surface, pg.Color("white"), (0, 0, tick_text_surface.get_width(), tick_text_surface.get_height()))
        self.render_surface.blit(tick_text_surface, (0, 0))
        
        scaled_surface = pg.transform.smoothscale(self.render_surface, (WIDTH, HEIGHT))
        self.screen.blit(scaled_surface, (0, 0))
        
        pg.display.flip()

    
    def run(self) -> None:
        running = True
        pg.time.set_timer(TIMER_EVENT, SIMULATE_SECONDS * 1000)

        while running:
            for event in pg.event.get():
                if event.type == pg.QUIT or pg.key.get_pressed()[pg.K_q]:
                    running = False
                elif event.type == pg.KEYUP and event.key == pg.K_SPACE:
                    self.fuzzer.tick(self.game)
                    self.ticks += 1
            self.draw()
            self.clock.tick(FPS)                    

        pg.quit()
        
if __name__ == "__main__":
    game =  Game("maps/skeld.txt", debug=True)
    fuzzer = Fuzzer(game, seed=SEED, enable_competency=False)
    gui = GUI(game, fuzzer, "maps/skeld_display.txt")
    gui.run()
    game.print_action_history(SEED)
