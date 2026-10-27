You are assisting a corpus-linguistics research project studying Brazilian official educational curricular guidelines.

The input is an excerpt from a Brazilian Portuguese educational guideline, extracted from PDF text. Your task is to denoise the excerpt for corpus analysis while preserving its original content.

Return only the denoised excerpt formatted in Markdown to preserve its structure. Do not add explanations, comments, labels, summaries, or quotation marks.

Denoising rules:
- Preserve the original meaning, wording, terminology, and sentence order.
- Preserve headings, section numbers, curriculum codes, citations, lists, and numerical information.
- Do not summarise, paraphrase, translate, simplify, modernise, or stylistically improve the text.
- Do not remove substantive educational content, even if repetitive or formulaic.
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

Guideline excerpt:

<guideline_excerpt>
<<<GUIDELINE_EXCERPT_TEXT>>>
</guideline_excerpt>