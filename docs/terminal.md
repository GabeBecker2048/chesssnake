---
title: In the terminal
---

`chesssnake play` is a board and a prompt. Play offline with nothing but the
package, or log in to a server and play other people.

## Offline

```sh
pip install chesssnake
chesssnake play --local
```

```
8  ♜  ♞  ♝  ♛  ♚  ♝  ♞  ♜
7  ♟  ♟  ♟  ♟  ♟  ♟  ♟  ♟
6  ·  ·  ·  ·  ·  ·  ·  ·
5  ·  ·  ·  ·  ·  ·  ·  ·
4  ·  ·  ·  ·  ·  ·  ·  ·
3  ·  ·  ·  ·  ·  ·  ·  ·
2  ♙  ♙  ♙  ♙  ♙  ♙  ♙  ♙
1  ♖  ♘  ♗  ♕  ♔  ♗  ♘  ♖
   a  b  c  d  e  f  g  h

alice (white) vs bob (black)  |  white to move
type `help` for commands

> e4
```

Both sides are played at the one keyboard. An offline game is not saved.

| Option | |
|---|---|
| `--white-name NAME`, `--black-name NAME` | names to show |
| `--me white` or `--me black` | play only that side |

## On a server

Install the client and say which server, once per shell (or put the line in
your shell profile):

```sh
pip install 'chesssnake[client]'
export CHESSSNAKE__CLIENT__API_URL=https://chess.example
```

Every command also takes `--api-url URL` instead. Then:

```sh
chesssnake login                 # asks for your username and password; remembered
chesssnake challenge bob         # --color white, black or random
chesssnake challenges            # pending challenges, with their ids
chesssnake accept 12             # accept one: the game starts
chesssnake games                 # your games in progress, with their ids
chesssnake play --vs bob         # or: chesssnake play --game 7
```

You play as the account you logged in as, and the board faces your side. Both
players run `play` on the same game. The game lives on the server, so you can
quit and come back, or carry on in [the browser](browser.html).

`chesssnake logout` ends the login; `chesssnake whoami` shows who you are. A
login lasts 30 days unless the server says otherwise.

## At the prompt

Type a move (see [Writing moves](moves.html)), or one of:

| Command | |
|---|---|
| `moves` | list every legal move |
| `board` | redraw the board |
| `flip` | view from the other side |
| `fen`, `pgn` | the position as FEN, the game as PGN |
| `draw` | offer a draw |
| `accept`, `decline` | answer a draw offer |
| `resign` | resign |
| `new` | after a game: challenge your opponent to a rematch, or accept theirs |
| `save PATH` | write a PNG of the board |
| `refresh` | check the server now |
| `help` | list the commands |
| `quit` | leave (also <kbd>Ctrl</kbd>+<kbd>D</kbd> or <kbd>Ctrl</kbd>+<kbd>C</kbd>) |

## Seeing your opponent's move

When the server has [live updates](live-updates.html) on, your opponent's move
appears the moment it is made, while you sit at the prompt. When it does not,
`play` says so at the start and checks the server every 10 seconds instead.

| Option | |
|---|---|
| `--refresh SECONDS` | how often to check without live updates (default 10; `0` never) |
| `--no-live` | do not use live updates, check on a timer instead |

On Windows, a live move shows when you next press Enter.

## Display options

| Option | |
|---|---|
| `--perspective white` or `black` | which side faces you |
| `--ascii` | draw pieces as letters instead of figurines |
| `--no-color` | no colour codes at all, for piping to a file |

Every command and option is listed in [Command line](cli.html).
