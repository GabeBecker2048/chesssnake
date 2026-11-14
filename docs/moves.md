---
title: Writing moves
---

Wherever you type or send a move (the terminal, Python, the REST API), it is
written in standard algebraic notation (SAN) or in UCI, the form chess engines
use. Both work everywhere.

| Move | SAN | UCI |
|---|---|---|
| Pawn push | `e4` | `e2e4` |
| Piece move | `Nf3`, `Bb5`, `Qh4` | `g1f3` |
| Capture | `exd5`, `Nxe5` | `e4d5`, `f3e5` |
| Two pieces can reach the square | `Nbd2`, `R1a3`, `Nexg4` | `b1d2` |
| Promotion | `e8=Q` or `e8Q` | `e7e8q` |
| Castling kingside | `O-O` or `0-0` | `e1g1` |
| Castling queenside | `O-O-O` or `0-0-0` | `e1c1` |

- Piece letters are capitals: `K`, `Q`, `R`, `B`, `N`. Pawns have no letter.
- A `+` (check) or `#` (checkmate) at the end is allowed and never needed.
- A capture needs its `x`: `Nxe5`, not `Ne5`, when there is a piece on e5.
- In UCI, castling is the king's move.

## What you get back

Whichever form you send, chesssnake answers and lists moves in one notation:
SAN with the promotion letter straight after the square (`e8Q`) and castling
written with zeros (`0-0`). Anything it shows you can be sent back as it is.

PGN export uses the standard `e8=Q` and `O-O`, so it opens in any chess tool.

## When a move is refused

An illegal move is refused with the reason, and nothing changes. The common ones:

| Error | Meaning |
|---|---|
| `InvalidNotationError` | That is not a move in either notation. |
| `PieceNotFoundError` | No piece of that kind can reach that square. |
| `MultiplePiecesFoundError` | More than one can: say which (`Nbd2`). |
| `MoveIntoCheckError` | It would leave your king in check. |
| `NothingToCaptureError` | You wrote a capture, and the square is empty. |
| `PieceOnSquareError` | There is a piece there: write it as a capture. |
| `CaptureOwnPieceError` | That is your own piece. |
| `PromotionError` | A pawn reaching the last rank must say what it becomes, and only then. |
| `InvalidCastleError` | Castling is not available. |
| `IllegalMoveError` | Not legal, with no more specific reason. |
| `NotYourTurnError` | It is the other player's move. |
| `GameOverError` | The game has ended. |

## How games end

A game ends by itself on checkmate, stalemate, threefold repetition, the
fifty-move rule, or insufficient material. Nobody has to claim a draw. It also
ends when a player resigns, or when a draw offer is accepted.
