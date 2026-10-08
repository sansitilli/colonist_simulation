# Results: wood port or wheat port

Game `256800428`, 4 players, 10 VP, base map. Play order Orange, Ushpuppy (green), Black, Blue. In the real game Ushpuppy won on turn 77.

## The decision

Turn 45, event 318. Hand `LLBBWGGG`, 5 VP. A road and a settlement were affordable, and two port spots were one road away:

| Branch | Road | Settlement | Hex | Port |
|---|---|---|---|---|
| `wood_port` (played) | 8–9 | corner 9 | wool 10 | lumber 2:1 |
| `grain_port` | 34–39 | corner 39 | ore 3 | grain 2:1 |

Both cost the same. The second wheat-port corner (38) is illegal: it touches Orange's settlement on corner 41. Ushpuppy did build road 34–39 later, with Road Building on turn 73.

What the two spots change:

- **Production.** After turn 45 the dice show one 10 and two 3s. Corner 9 adds one wool. Corner 39 adds two ore, and ore is Ushpuppy's bottleneck (his only ore hex is ore 3; each city needs three).
- **Trading.** Ushpuppy's lumber 8 city produces about 10 lumber he has no use for. The wood port turns that into useful cards at 2:1. The wheat port trades away grain, which his cities and development cards consume.
- **Timing.** Which purchases are affordable on which turn changes when he draws development cards, and therefore which cards he and everyone else receive.

## Assumptions

- **Policy.** Every player uses the adaptive policy.
- **Deck.** Positional: the deck is a fixed stack, in the order recorded in the replay.
- **Dice.** The recorded dice are used up to turn 77, then random dice for everyone.
- **Runs.** 1000 runs per branch. Runs differ in steal outcomes, the order of the 9 undrawn cards, and dice after turn 77.

The engine is checked against the replay itself. All four hands are rebuilt from parsed actions at all 274 snapshots, production is reproduced for all 54 non-seven rolls, and the draw order matches all 16 visible purchases. Replaying the wood branch with Ushpuppy's real purchases reproduces his win on turn 77 (`tests/test_engine.py`).

## Main result

| Branch | Ushpuppy wins | Within the record | Winners |
|---|---|---|---|
| `wood_port` | 12.3% | 12.1% | Black 49.4%, Blue 38.3%, Ushpuppy 12.3% |
| `grain_port` | **100%** | **100%** (always turn 77) | Ushpuppy 100% |

Paired by seed, the wheat port turns a loss into a win in 87.7% of runs and never the other way around.

### Why

Typical wood run (`colonist-cf trace … --branch wood_port --seed 2`):

```
t61: city 37                      lumber 2:1 makes the city affordable one turn early
t63: Blue draws victory_point     the VP card Ushpuppy took on turn 61 in the real game
t65: city 35, bought knight
t69: city 9                       9 VP, no second VP card
t77: 9 VP
t79: Blue monopoly grain +10, city, settlement, 11 VP
```

Typical wheat run (`--branch grain_port --seed 2`):

```
t61: bought victory_point         no 2:1 port for lumber, so a card instead of a city
t65: city 37, bought monopoly
t69: monopoly ore +5, city 35     9 VP
t77: city 39                      grain 2:1 into ore, 10 VP
```

The wood port lets Ushpuppy build a city on turn 61 instead of buying a development card. That card was a victory point, and in the positional deck it then goes to Blue on turn 63. Ushpuppy ends the record on 9 VP. Black has been on 9 VP since turn 66 and moves first on turn 78, and Blue picks up the VP card plus a monopoly. With the wheat port, the turn-61 purchase is the card, and the fourth city on corner 39 is fed by the extra ore from ore 3 and by 2:1 grain into ore.

So the advantage is partly structural (ore beats wool for a city-heavy hand) and partly deck timing (the wheat branch draws the card that wins). Both count under the assumption that the deck order is known, which is the question asked.

## Supporting results

### Best possible play with hindsight

`colonist-cf oracle --seeds 10 --beam 80` finds the earliest win reachable inside the record, knowing every die and card:

| Deck model | `wood_port` | `grain_port` |
|---|---|---|
| positional | turn 77 | **turn 69** |
| queue | turn 69 | turn 69 |

Wheat line, positional deck:

1. Turn 61: buy a VP card.
2. Turn 65: city on 37, buy Monopoly.
3. Turn 69: Monopoly on ore (+5), city on 35, grain→ore 2:1, city on 39.

That reaches 10 VP with four cities and two VP cards, and never needs the last VP card in the deck. The best wood line has to wait until turn 77.

### Everyone adaptive from the decision

In the main result the opponents replay their recorded moves until turn 77. Here every player is simulated by the adaptive policy from turn 46, so the opponents react to the different board and hands. The second row also drops hindsight on the dice.

| Mode | Dice and deck | `wood_port` wins | `grain_port` wins | Paired: only wheat / only wood |
|---|---|---|---|---|
| `--from-decision` | recorded to turn 77, random after; recorded deck order | 37.3% | **42.6%** | 24.7% / 19.4% |
| `--from-decision --random-dice` | random from turn 46; recorded deck order | 52.1% | 55.9% | 18.9% / 15.1% |

With the same dice and cards to turn 77, the wheat port still comes out ahead, by about 5 points. The margin is much smaller than in the main result because adaptive opponents play differently from the real ones: Black no longer sits on 9 VP from turn 66, and games run longer (mean winning turn about 88 for both branches). With random dice the two branches are within noise of each other, so at the table, without knowledge of the future, the wood port was a reasonable choice.

### Sensitivity

| Variant | `wood_port` | `grain_port` |
|---|---|---|
| queue deck, adaptive | wins 100%, turn 73 in 86% | wins 100%, turn 77 |
| positional deck, Ushpuppy repeats his real purchases as early as affordable | Black wins turn 70 | Black wins turn 70 |

Under the queue model Ushpuppy keeps his own cards regardless of timing. The structural trading argument then favours wood (lumber 2:1 converts his surplus), and the wood port wins about one round earlier.

The second row shows how sharp the deck trap is. Buying a development card on turn 69, a few turns earlier than in the real game, shifts the last VP card to Black, who sits on 9 VP and wins on turn 70. In the real game Ushpuppy could not afford that card until turn 77, which is what saved him.

## Answer

Knowing the dice and the deck order, **yes: the wheat port was the better build.** Against the opponents' real moves it turns a 12% game into a 100% win on turn 77. Under perfect play it wins on turn 69 against turn 77. With every player adaptive from the decision and the same dice and cards, it still wins more often (42.6% against 37.3%).

The edge comes from the extra ore and from drawing the right card at the right time, not from the port in isolation. Without hindsight the two options are equal, and if Ushpuppy's own card sequence is held fixed, wood is slightly better.

## Consistency notes

Reported by `run` and `trace`, these mark places where the counterfactual departs from the record more than the model can re-simulate:

- **Blue draws a different card.** Blue's turn-67 draw changes with the deck shift, but Blue still plays the recorded knights on turns 71 and 75. Both robbed Black, not Ushpuppy.
- **Black's turn-70 purchase.** In some runs Black pays for its recorded development card with ore that Ushpuppy's monopoly took in the counterfactual.
- **Ushpuppy's knights.** When Ushpuppy plays a knight before turn 77, the robber moves for his production only. The opponents' recorded production is kept.

None of these touches Ushpuppy's production or victory points before turn 77.

## Reproduce

```bash
colonist-cf audit data/game_256800428.json
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 1000 --json results/main.json
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 1000 --from-decision --json results/all_adaptive.json
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 1000 --from-decision --random-dice --json results/no_hindsight.json
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 500 --deck queue --json results/queue_deck.json
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 500 --policy scripted --json results/recorded_plan.json
colonist-cf oracle scenarios/ushpuppy_port_choice.json --seeds 10 --beam 80 --show-line
colonist-cf oracle scenarios/ushpuppy_port_choice.json --seeds 10 --beam 80 --deck queue
```

Raw outputs are in `results/`.
