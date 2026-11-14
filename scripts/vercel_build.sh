#!/bin/sh
# Assemble the static site for Vercel into public/. No Python needed at deploy time.
# Files under docs/ are optional: if they are not in the repo, the page still deploys.
set -e
rm -rf public
mkdir -p public
cp web/index.html public/index.html
copy() { [ -f "$1" ] && { mkdir -p "public/$(dirname "$2")"; cp "$1" "public/$2"; } || echo "skip (not in repo): $1"; }
copy docs/concept-card.pdf docs/concept-card.pdf
copy docs/concept-card.html docs/concept-card.html
copy docs/deck/index.html docs/deck/index.html
copy docs/deck/deck.pdf docs/deck/deck.pdf
[ -d docs/deck/img ] && { mkdir -p public/docs/deck; cp -R docs/deck/img public/docs/deck/img; } || echo "skip (not in repo): docs/deck/img"
