# Put your submission here

One file. Name it whatever you like.

| Accepted | Notes |
|---|---|
| `.md` | preferred — nothing to go wrong |
| `.txt` | fine |
| `.docx` | text and tables are read; images are not |
| `.pdf` | text-based PDFs only, not scans |

Then, from the repository root:

```bash
python task_1/judge.py
```

If there is more than one file here, the most recently modified one is graded
and the others are named in the output. To pick one explicitly:

```bash
python task_1/judge.py --file task_1/submissions/our_design.md
```

## About the diagram

The judge reads text. It cannot see an image, and it cannot see a photograph of
a whiteboard.

If your diagram is a picture, the judge will say so in its report and grade the
structure from your component descriptions instead — which means those
descriptions have to carry it. The safer route is to include the diagram as
ASCII or Mermaid as well, which takes two minutes and costs you nothing.

This file is ignored by the judge.
