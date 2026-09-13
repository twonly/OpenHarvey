# Third-party browser libraries

- `docx-preview-0.3.6.min.js` is from
  [VolodymyrBaydalka/docxjs](https://github.com/VolodymyrBaydalka/docxjs),
  package `docx-preview@0.3.6`, licensed under Apache-2.0. The complete license
  text is stored in `docx-preview-LICENSE`.
- `jszip-3.10.1.min.js` is from
  [Stuk/jszip](https://github.com/Stuk/jszip), package `jszip@3.10.1`, licensed
  under MIT or GPL-3.0-or-later. The complete license text is stored in
  `jszip-LICENSE`.

Both files are vendored so the contract workspace can render Word documents
without contacting a public CDN at runtime.
