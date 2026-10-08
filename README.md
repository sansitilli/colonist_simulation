# Catan Simulation

Counterfactual replays of [Colonist.io](https://colonist.io) games. Take a finished game, change one decision, keep everything that was not caused by that decision (dice, the order of the development deck, the opponents' recorded moves), and measure who wins.

The bundled example asks a single question about game `256800428`:

> On turn 45 Ushpuppy (green) built a settlement on the **wood 2:1 port**. Knowing the dice and the development card order, would the **wheat 2:1 port** have been better?

Short answer: **yes**. With the wheat port Ushpuppy wins on turn 77 in every simulated continuation. With the wood port he wins only 12% of the time; Black (sitting on 9 VP since turn 66) or Blue win the rest. Details, tables and the reasoning are in [RESULTS.md](RESULTS.md).

## How it works

```
replay JSON ──► parser ──► normalized actions + full hand snapshots
                                 │
                                 ├─► audit: rebuild every hand from actions, compare with snapshots
                                 │
decision branch ──► counterfactual engine (recorded dice and opponents, adaptive hero)
                                 │
                       end of record (turn 77)
                                 │
                                 ▼
                    full 4-player game, random dice, adaptive for everyone
```

**Parser and board.** Colonist stores the board as axial hex coordinates with corner and edge indices. `board.py` rebuilds the geometry (54 corners, 72 edges, 9 ports). The orientation of edges was derived from the setup placements and is verified by the audit: computed production matches all 54 non-seven rolls for all four players.

**Audit.** The replay exposes every player's hand after every change. `colonist-cf audit` rebuilds each hand purely from parsed actions (production, steals, discards, trades, builds, development cards, monopolies) and compares it with all 274 snapshots. Any mismatch means the parser misunderstands the log, so this runs before any simulation result is trusted.

**Counterfactual engine.** From the decision event on, the hero's recorded actions are dropped and replaced by a policy. Opponents keep their recorded actions, and their hands are tracked as `recorded hand + adjustment`. The adjustment changes only where the hero interacts with them:

- a steal from the hero takes a random card from the hero's counterfactual hand;
- a monopoly takes whatever the counterfactual hands actually hold;
- the hero's own monopoly and steals are re-resolved against counterfactual hands;
- a development card drawn by an opponent can change when the hero buys at different times (see deck models).

Production, the robber, the bank, discards on sevens and victory points are recomputed for the hero and checked for the opponents. Where an opponent's recorded move becomes impossible in the counterfactual (for example a purchase paid with ore the hero has just taken), it is applied anyway and reported as a consistency note, so the size of the divergence stays visible.

**Development deck.** The replay's end state contains the exact draw order of all 16 cards drawn during the game. The 9 undrawn cards are unknown and are shuffled per run. Two models:

- `positional` (default): the deck is a fixed stack and every purchase takes the next card, whoever buys it. Buying earlier or later than in the real game changes which cards everyone receives. Opponents' victory points follow their counterfactual cards, so an opponent can win because of a deck shift.
- `queue`: the hero always receives the next card he drew in the real game; opponents keep their recorded cards. Useful as a sensitivity check.

**After the record.** The game ended on turn 77 because Ushpuppy won. If a branch has no winner by then, the simulation continues as a complete four-player game: random dice, the remaining deck, robber and steals, discards, monopolies, Largest Army and Longest Road recomputed, everyone playing the adaptive policy.

**Policies.**

- `adaptive`: each turn play a useful development card (knight if the robber blocks you, monopoly when it completes a purchase or yields at least five cards, year of plenty or road building when they complete a purchase), then buy in the order city, settlement (up to two new roads), development card, using the cheapest bank and port trades; trade down toward the next purchase when holding more than seven cards; discard to protect the next purchases.
- `scripted`: the hero repeats the purchases he made in the real game after the decision, each as early as it becomes affordable.
- `oracle` (command): a beam search that knows the dice and the deck and looks for the earliest possible win inside the record. It is an upper bound on what the branch allows, not a playable strategy.

## Requirements and installation

Python 3.10+, no runtime dependencies.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Usage

```bash
colonist-cf audit data/game_256800428.json
colonist-cf inspect data/game_256800428.json --player Ushpuppy
colonist-cf candidates data/game_256800428.json --player Ushpuppy --event 318

colonist-cf run scenarios/ushpuppy_port_choice.json --runs 1000
colonist-cf run scenarios/ushpuppy_port_choice.json --runs 1000 --from-decision
colonist-cf run scenarios/ushpuppy_port_choice.json --deck queue
colonist-cf run scenarios/ushpuppy_port_choice.json --policy scripted
colonist-cf oracle scenarios/ushpuppy_port_choice.json --seeds 10 --beam 80 --show-line
colonist-cf trace scenarios/ushpuppy_port_choice.json --branch grain_port --seed 1
```

`candidates` lists every legal settlement spot at a given event with the roads it needs, its production and its port, which is the quickest way to define new branches.

## Scenario files

```json
{
  "replay": "../data/game_256800428.json",
  "hero": "Ushpuppy",
  "decision": {"start": 318, "end": 320},
  "branches": {
    "wood_port": {"roads": [[8, 9]], "settlement": 9},
    "grain_port": {"roads": [[34, 39]], "settlement": 39}
  },
  "policy": {"name": "adaptive", "monopoly_threshold": 5, "max_new_roads": 2},
  "opponent_policy": {"name": "adaptive"},
  "deck": {"mode": "positional", "known_order": null},
  "continue_turns": 160,
  "runs": 1000,
  "seed": 1
}
```

- `decision.start` / `decision.end`: replay event indices of the decision being replaced (find them with `inspect --player`). From `start` on, the hero's recorded actions are replaced by the policy.
- `branches`: what the hero builds instead, at `start`. Roads are given as corner pairs. Each branch is checked for legality and affordability.
- `deck.known_order`: optional full or partial card order (Colonist card ids 11–15) if you know more than the replay records.

## Exporting a replay from Colonist

You can only export games that your account can open as a replay.

1. Log in to colonist.io and open the replay. The address looks like `https://colonist.io/replay?gameId=256800428&playerColor=4`.
2. In the same browser, open
   `https://colonist.io/api/replay/data-from-game-id?gameId=<gameId>&playerColor=<playerColor>`
   with the same two numbers. The browser shows JSON.
3. Save the page (Ctrl+S / Cmd+S) as `data-from-game-id.json`.

Alternative: open DevTools → Network, reload the replay, filter for `data-from-game-id`, and copy the response. Saving a HAR file usually does not work, because browsers often leave response bodies out of HAR exports.

`playerColor` is the perspective you watch from. In this replay every player's hand is visible in the data, not only the exporting player's.

Before committing a replay, anonymize it:

```bash
colonist-cf anonymize data-from-game-id.json data/game_<id>.json --keep YourName
colonist-cf audit data/game_<id>.json
```

This replaces the other usernames with their colours (Red, Blue, Orange, Green, Black), deletes the chat, user ids and country codes, and keeps everything the simulation needs. The bundled file was produced this way.

## Data and terms

The replay is fetched by hand, by a logged-in player, from a page that Colonist serves to that player. No scraping is involved, and the project contains no Colonist code or assets. Colonist's Terms of Service are the authority on whether replay data may be republished. If in doubt, read them or ask Colonist, and publish the code without `data/`. Everything still works with a replay supplied locally.

## Project layout

```
src/colonist_cf/
  board.py       hex geometry, ports, trade ratios
  replay.py      replay JSON to normalized actions and snapshots
  audit.py       hand and production reconstruction check
  cards.py       resource multiset
  trading.py     cheapest bank/port trade plan for a purchase
  deck.py        development deck models
  engine.py      counterfactual replay of the recorded game
  fullgame.py    four-player continuation after the record
  policy.py      adaptive and scripted policies
  oracle.py      clairvoyant beam search
  scenario.py    scenario loading and Monte Carlo summaries
  anonymize.py   username and chat removal
  cli.py         command line
scenarios/       experiment definitions
data/            anonymized replay
results/         outputs behind RESULTS.md
tests/
```

## Limitations

- Opponents follow the record until the record ends. They do not react to the hero's different choices before turn 77, apart from the forced effects listed above.
- Trades between players are not proposed by the policies. Ushpuppy made no player trades after the decision in this game.
- The adaptive policy is a reasonable heuristic, not an expert. Both branches use the same policy, so the comparison is fair, but absolute win rates depend on it.
- After the record the robber targets the strongest adjacent opponent, and dice are fair. The continuation measures the position, not the people who played it.
