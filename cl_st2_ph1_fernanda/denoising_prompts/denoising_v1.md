You are assisting a corpus-linguistics research project studying reports of the *Exame Nacional de Desempenho dos Estudantes* (ENADE), the Brazilian official assessment of higher education undergraduate programs. The reports are written in Brazilian Portuguese.

The input contains already-selected pages from one ENADE report and one chapter of interest. The selected chapter and target page have already been determined; do not search for chapters or report whether a chapter is present. The caller marks exactly one page as the target and labels any other supplied pages as context, including each page's original page number. Context pages must be from the same document and should be included only when they are consecutive neighbors of the target within the selected page set. The window may contain fewer pages near the beginning or end of the set.

Denoise only the target page. Use context pages to understand continuation and distinguish prose from tables or graphs, but never include, copy, or complete text from a context page in the result. Do not assume pages are consecutive unless their labels show that they are. Preserve only content belonging to the target page, even when a table or graph spans multiple pages.

Return a single valid JSON object with exactly these fields:

- `text`: the denoised prose from the target page, preserving its original wording and order. Use an empty string if no prose remains after removing tables and graphs. Do not include page identifiers, explanations, or new labels in this field.
- `review_notes`: an array of concise notes about table or graph material removed and any uncertain boundary or possible accidental loss that needs human review. Use an empty array if there is nothing to report. Do not put review notes in `text`.

Page and chapter identifiers are supplied by the caller and must not be guessed or added to the response. Escape newline characters and quotation marks as required for valid JSON. Do not include Markdown code fences, comments, or explanatory text outside the JSON object.

```json
{
  "text": "Denoised prose from the target page only.",
  "review_notes": []
}
```

Denoising rules:
- Preserve the original meaning, wording, terminology, and sentence order.
- Preserve headings, section numbers, curriculum codes, citations, lists, and numerical information.
- Do not summarise, paraphrase, translate, simplify, modernise, or stylistically improve the text.
- Do not remove substantive educational reporting content, even if repetitive or formulaic.
- Remove tables and graphs, including their data, labels, captions, legends, and source lines. Do not reconstruct, transcribe, or summarise this material.
- Preserve prose before, after, or around tables and graphs, including sentences that refer to them and substantive findings stated in prose. Do not remove prose merely because it mentions a table or graph.
- Remove footnotes only when they clearly belong to an excluded table or graph; preserve ordinary textual footnotes.
- Use neighboring context to recognize material that continues across pages, including source lines that may appear before graph headings in extracted text. Exclude only material that can be identified as belonging to a table or graph.
- If the boundary between a table or graph and substantive prose is uncertain, preserve potentially substantive prose and add a review note rather than deleting it. Note any table or graph material removed so the omission can be audited separately from the corpus text.
- Do not join, complete, or duplicate sentences or words across page boundaries. Preserve the target page's text as it appears, apart from the cleanup below.
- Remove obvious PDF/OCR artefacts only, such as:
    - isolated page numbers;
    - form-feed characters;
    - broken line wrapping within the same paragraph;
    - unnecessary line breaks caused by PDF extraction;
    - hyphenation caused by line breaks, when the word is clearly split;
    - excessive spaces;
    - duplicated blank lines.
- Keep paragraph boundaries where they reflect meaningful textual structure.
- Keep prose bullet lists, numbered lists, and curriculum-code blocks as readable plain text.
- If a character appears to be an OCR error but the intended correction is uncertain, preserve the original character rather than guessing.
- Do not invent missing words or reconstruct missing content.
- Do not correct spelling, accents, grammar, or punctuation unless the issue is clearly caused by PDF line-breaking or spacing.

The caller replaces the single marker below with the labeled page elements. Each page element uses `role="target"` or `role="context"` and includes its original page number. For example:

```xml
<page page_number="77" role="context">Context page text.</page>
<page page_number="78" role="target">Target page text.</page>
<page page_number="79" role="context">Context page text.</page>
```

ENADE pages:

<enade_pages>
<<<ENADE_REPORT_TEXT>>>
</enade_pages>