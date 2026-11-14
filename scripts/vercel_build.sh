#!/bin/sh
# Assemble the static site for Vercel into public/. No Python needed at deploy time.
set -e
rm -rf public
mkdir -p public/docs/deck
cp web/index.html public/index.html
cp docs/concept-card.pdf public/docs/concept-card.pdf
cp docs/concept-card.html public/docs/concept-card.html
cp docs/deck/index.html docs/deck/deck.pdf public/docs/deck/
cp -R docs/deck/img public/docs/deck/img
