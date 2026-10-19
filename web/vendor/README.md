# Bundled browser libraries

These versioned upstream files ship with the skill. The viewer never loads a CDN
or requires npm at runtime. Do not edit the vendor JavaScript files by hand.

- **Marked 17.0.5** — https://github.com/markedjs/marked — MIT, see
  `marked-LICENSE.md`. `marked-17.0.5.js` is upstream `lib/marked.umd.js`.
- **DOMPurify 3.4.17** — https://github.com/cure53/DOMPurify — MPL-2.0 OR
  Apache-2.0, see `dompurify-LICENSE`. `dompurify-3.4.17.js` is upstream
  `dist/purify.min.js`. The npm package SHA-512 integrity was verified on download.

Markdown is parsed with Marked and sanitized with DOMPurify before insertion.
Only document formatting tags are permitted. Raw HTML is escaped, links are
restricted to HTTP/HTTPS/mailto or discussion event anchors, and Markdown images
are shown as links so a message cannot trigger an automatic remote image request.
