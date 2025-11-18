#!/usr/bin/env python

from game import Game
from fuzzer import Fuzzer
import matplotlib.pyplot as plt

MAX_TICKS = 50_000
START_SEED = 1
END_SEED = 10000

def run_single(seed: int, setup_file: str, double_up: bool) -> tuple[int, str, int]:
    game = Game(setup_file)
    fuzzer = Fuzzer(game, seed=seed, group_size=2 if double_up else 1 + 3)

    while True:
        fuzzer.tick(game)

        if game.check_crewmate_win():
            return seed, "crewmate", game.tick_counter

        if game.check_imposter_win():
            return seed, "imposter", game.tick_counter

        if game.tick_counter >= MAX_TICKS:
            return seed, "timeout", game.tick_counter


def run_bulk(setup_file: str, double_up: bool) -> list[tuple[int, str, int]]:
    results = []
    for seed in range(START_SEED, END_SEED + 1):
        result = run_single(seed, setup_file, double_up)
        results.append(result)
        print(result)
    return results

def plot_results_comparison(double_up_results, k_results, image_path="results.png") -> None:
    def counts(data) -> tuple[int, int, int]:
        return (
            sum(1 for r in data if r[1] == "crewmate"),
            sum(1 for r in data if r[1] == "imposter"),
            sum(1 for r in data if r[1] == "timeout")
        )

    d_crew, d_imp, d_timeout = counts(double_up_results)
    k_crew, k_imp, k_timeout = counts(k_results)

    labels = ["Crewmate", "Imposter", "Timeout"]
    double_vals = [d_crew, d_imp, d_timeout]
    k_vals = [k_crew, k_imp, k_timeout]

    x = range(len(labels))
    width = 0.35

    plt.figure(figsize=(10, 6))
    plt.bar([i - width/2 for i in x], double_vals, width, label="Double-Up", color="blue", alpha=0.7)
    plt.bar([i + width/2 for i in x], k_vals,      width, label="K",         color="red",  alpha=0.7)

    plt.xticks(list(x), labels)
    plt.ylabel("Win count")
    plt.title("Strategy Win Count Comparison")
    plt.grid(axis="y", linewidth=0.2)
    plt.legend()

    plt.tight_layout()
    plt.savefig(image_path, dpi=300)
    plt.show()

if __name__ == "__main__":
    double_up_results = run_bulk("maps/skeld.txt", True)
    k_results = run_bulk("maps/skeld.txt", False)
    plot_results_comparison(double_up_results, k_results)
