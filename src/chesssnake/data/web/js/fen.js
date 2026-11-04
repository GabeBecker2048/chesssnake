// Reading a FEN: where the pieces are and whose turn it is. Nothing here knows
// the rules; the server decides what is legal (GET /games/{id}/legal-moves).

export const FILES = "abcdefgh";

/**
 * Parse a FEN into {squares, turn}: squares maps "e4" -> {color: "w"|"b", type: "K"|...}.
 */
export function parseFen(fen) {
  const [placement, turn = "w"] = fen.split(" ");
  const squares = new Map();
  placement.split("/").forEach((row, i) => {
    const rank = 8 - i;
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) {
        file += Number(ch);
      } else {
        const color = ch === ch.toUpperCase() ? "w" : "b";
        squares.set(`${FILES[file]}${rank}`, { color, type: ch.toUpperCase() });
        file += 1;
      }
    }
  });
  return { squares, turn };
}

/** The image for a piece: the same sprites the API renders boards with (K0 = white king). */
export function pieceSrc(piece) {
  return `/assets/pieces/${piece.type}${piece.color === "w" ? 0 : 1}.png`;
}

/** The squares of the board, top-left first, as seen from `orientation`. */
export function squaresFrom(orientation) {
  const out = [];
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      const file = orientation === "white" ? col : 7 - col;
      const rank = orientation === "white" ? 8 - row : row + 1;
      out.push(`${FILES[file]}${rank}`);
    }
  }
  return out;
}

export function isDark(square) {
  const file = FILES.indexOf(square[0]);
  const rank = Number(square[1]);
  return (file + rank) % 2 === 1; // a1 (0 + 1) is dark, h1 (7 + 1) light
}
