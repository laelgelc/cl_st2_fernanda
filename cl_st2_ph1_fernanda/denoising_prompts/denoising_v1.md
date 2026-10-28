You are assisting a corpus-linguistics research project studying reports of the *Exame Nacional de Desempenho dos Estudantes* (ENADE), the Brazilian official assessment of higher education undergraduate programs. The reports are written in Brazilian Portuguese.

The input is an ENADE report extracted from a PDF document. Your task is to denoise selected chapters of the report for corpus analysis while preserving its original content.

Three chapter types titled as follows (case-insensitive) are of interest. Use the following internal labels, regardless of the chapter number in the source report:

- `c4`: chapter titled *percepção sobre a prova* or *percepção da prova*
- `c5`: chapter titled *distribuição dos conceitos* or *distribuição de conceitos*
- `c6`: chapter titled *análise técnica da prova*

Do not infer a chapter type from the chapter number alone; identify chapters by title.

Return a single valid JSON object that follows exactly this structure:

- In the "chapters" field, return only the denoised Markdown text of the selected chapters, in the order they appear. Do not add explanations, comments, new labels, summaries, or quotation marks.
- In the "metadata" field, set each value to true only if the corresponding chapter type was found and included in "chapters"; otherwise, set it to false.
- If none of the selected chapter types is present, return an empty string in "chapters" and set all metadata values to false.
- Ensure the response is valid JSON. Escape newline characters and quotation marks inside the "chapters" string as required by JSON.

```json
{
  "chapters": "Denoised Markdown text of the selected chapters, in the order they appear.",
  "metadata": {
    "c4_present": true,
    "c5_present": true,
    "c6_present": true
  }
}
```

Do not include Markdown code fences, comments, or explanatory text outside the JSON object.

Denoising rules:
- Preserve the original meaning, wording, terminology, and sentence order.
- Preserve headings, section numbers, curriculum codes, citations, lists, and numerical information.
- Do not summarise, paraphrase, translate, simplify, modernise, or stylistically improve the text.
- Do not remove substantive educational reporting content, even if repetitive or formulaic.
- Remove obvious PDF/OCR artefacts only, such as:
    - isolated page numbers;
    - form-feed characters;
    - broken line wrapping within the same paragraph;
    - unnecessary line breaks caused by PDF extraction;
    - hyphenation caused by line breaks, when the word is clearly split;
    - excessive spaces;
    - duplicated blank lines.
- Keep paragraph boundaries where they reflect meaningful textual structure.
- Keep tables, bullet lists, numbered lists, and curriculum-code blocks as readable plain text.
- If a character appears to be an OCR error but the intended correction is uncertain, preserve the original character rather than guessing.
- Do not invent missing words or reconstruct missing content.
- Do not correct spelling, accents, grammar, or punctuation unless the issue is clearly caused by PDF line-breaking or spacing.

ENADE report:

<enade_report>
<<<ENADE_REPORT_TEXT>>>
</enade_report>