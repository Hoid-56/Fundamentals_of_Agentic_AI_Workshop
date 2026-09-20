# Task 1 — Architecture Design

**Format:** individual or pairs · **Time:** 60 minutes · **Deliverable:** one document · **No code**

---

## Why this task comes first

Everything specific you learn about agentic AI this month will be wrong within
the year.

The model that tops the benchmark today will be deprecated. The framework you
learn will be rewritten, or abandoned, or replaced by something with a better
README. The context window will grow by an order of magnitude and half of what
people call "advanced RAG" will stop being necessary. The pricing will change.
The tool-calling format will change. It has changed twice already while this
workshop was being written.

None of that is a reason to despair, and none of it is a reason to wait for
things to settle. It is a reason to be careful about *what you actually learn*.

There are two ways to know this field.

The first is to know the current answers. Which model is best at code. Which
orchestration library is fashionable. Which chunking strategy someone
benchmarked well last quarter. This knowledge is genuinely useful and it has a
half-life measured in months. People who have only this are fluent right up
until the day the ground moves, and then they are starting over.

The second is to know why the answers are what they are. What a transformer
actually does with a sequence, and why that makes context expensive and recall
imperfect. Why a model that predicts tokens has no notion of having *done*
anything, and what has to be built around it before it can act. Where latency
comes from in an agent loop, and where cost comes from, and why those two pull
in opposite directions. Which failures are the model's and which are the
system's. What a tool call is actually costing you, in money, in latency, and
in attack surface.

That second kind does not expire. When the model changes, you already know
which of your assumptions it invalidates. When a new pattern appears, you can
tell in ten minutes whether it solves a problem you have. When something
breaks in production at 2am, you know which layer to look at — and that is the
difference between an engineer who is quick and one who is merely current.

**This task tests the second kind, and only the second kind.**

You will not write a line of code. You will not run anything. You will be
handed a real set of requirements and asked to design a system that meets
them, and then to explain *why* your design is shaped the way it is. The
grading weights your reasoning above everything else — a modest architecture
whose trade-offs you can defend will score higher than an elaborate one you
cannot.

One more thing, stated plainly because it matters: you may use an AI assistant
for this. It will happily hand you a diagram with seven agents, four
frameworks and a vector database. It will not tell you why you need any of
them, because it does not know your constraints and it has not read them. The
gap between what it gives you and what you submit is exactly the thing being
measured.

---

## What you are designing

Banco Ejemplo wants a customer assistant. It answers questions about products
and about the customer's own account, and it can take a small number of
actions on that account. It is the same system you will spend the afternoon
hardening, so the requirements below are real, not illustrative.

Design a **multi-agent architecture** for it, covering retrieval over the
bank's documentation, transactional operations on customer accounts, memory
across a conversation, and observability.

### Scale and constraints

Design against these numbers. They are what make the interesting decisions
interesting.

| | |
|---|---|
| Customers | 50,000 active |
| Conversations | ~8,000 per day, 3x at month-end and after any outage |
| Turns per conversation | 4 on average, long tail to 30 |
| Latency budget | first token under 2s, full answer under 6s |
| Availability | the card-blocking path must work when everything else is degraded |
| Regulated | every action on an account must be auditable and attributable |
| Languages | Spanish and English |

Budget is not unlimited and nobody will tell you the number. Part of the task
is deciding what you would spend money on and what you would not, and saying
why.

---

## Functional requirements

All of this is in scope. The assistant must be able to do all of it.

### Public information — no sign-in needed
Product details (fees, limits, contactless limits, foreign transaction fees,
ATM rules), the lost or stolen card procedure, transaction disputes, transfer
types and costs, opening hours, and interest and charges.

This lives in a product document. If it is not in that document, the assistant
does not know it.

### The signed-in customer's own account
List their cards; balance, credit limit and expiry for each; transaction
history; transactions filtered to one card; spend at a named merchant.

### Confidential transactions
Some transactions are marked confidential. Whether they may be discussed
depends on the account — see *Segments and entitlements* below.

### Account preferences
Paperless billing, statement language, marketing consent, home branch.

### Actions on the account
Freeze a card, unfreeze a card, and open a dispute on an unrecognised
transaction. These are irreversible from the assistant's side and are
therefore treated differently from everything above.

### Segments and entitlements
Customers belong to a segment, and segments differ in what they may do.
Neither segment is simply more trusted than the other — each can do something
the other cannot:

| | retail | business |
|---|---|---|
| discuss confidential transactions without re-authenticating | no | **yes** |
| freeze a card | **yes** | no |

### Strictly out of scope
The assistant declines politely and redirects. It never attempts these, never
improvises, never invents a number:

- Mortgages and any lending recommendation
- Financial, investment or pension advice of any kind
- Making a transfer or payment on the customer's behalf
- Closing an account, or deleting a card or product
- Permanently cancelling a card — a freeze is temporary and is not the same
- Anything belonging to a merchant rather than to the bank

---

## What to hand in

One document. Markdown, PDF, Word or plain text. **Six pages is plenty** and
four is often better.

### 1. Architecture diagram
A schema showing your components and how they talk to each other. ASCII is
fine. Mermaid is fine. A table of edges is fine. Legibility is what matters,
not tooling.

> One practical constraint: **the judge reads text and cannot see images.**
> Draw on a whiteboard by all means — that is usually the faster way to think
> — but what you hand in has to contain the structure in text, or the
> component descriptions will have to carry it alone. Transcribing a diagram
> into Mermaid takes two minutes.

### 2. A short description of every component
For each box on your diagram, in a few sentences:

- what it does
- what it is allowed to touch
- **why it exists as a separate component rather than being folded into
  another one**

That third point is the one that is actually being read.

### 3. Your agent decomposition, stated explicitly
- How many agents, and what each one is responsible for
- What makes something worth being its own agent here
- What you deliberately did *not* split out, and why

There is no correct number. There are defensible numbers and arbitrary ones.

### 4. Frameworks and patterns
Name what you would build with, and say why for each. "LangGraph" is not an
answer. "LangGraph, because the routing here is a state machine with
conditional edges and I want the graph to be inspectable in traces" is an
answer.

Same for patterns: router, supervisor, plan-and-execute, reflection, tool-use
loop, human-in-the-loop, whatever you reach for. Say what it buys you *in this
system*.

### 5. Retrieval design
How the product document is indexed, retrieved and kept current. What you do
when retrieval returns nothing useful. How you keep the assistant from
answering questions the document does not cover.

### 6. Memory management
What is remembered, at what scope, for how long, and what evicts it. Be
specific about the difference between what the model needs in context and what
the system needs in storage — they are not the same thing and conflating them
is the most common mistake in this section.

### 7. Observability
What you measure, what you log, what you alert on. Assume someone will ask you
next quarter why the assistant told a customer the wrong fee on a Tuesday in
March. Your design should make that answerable.

### 8. Trade-offs and what you would do differently with more budget
Where you knowingly took the cheaper or simpler option. What breaks first as
volume grows. What you would build if this were v2.

**This section is worth more than any other.** A design with a clear-eyed
account of its own limits beats one that pretends it has none.

---

## How it is graded

An LLM judge scores the submission on five dimensions. The rubric is published
here rather than hidden, because the point is to design well, not to guess what
we want.

| Dimension | Weight | What it looks for |
|---|---|---|
| **Design reasoning** | **35%** | Are choices justified? Are alternatives named and rejected for stated reasons? Are failure modes acknowledged? |
| **Scalability** | 20% | Does it hold at 3x? Where is the bottleneck, and does the design know? |
| **Cost efficiency** | 20% | Model routing, caching, and knowing when *not* to call a model |
| **Functional granularity** | 15% | Is the decomposition earned? Both too few and too many components are penalised |
| **Requirements coverage** | 10% | Does it actually serve the spec, including the out-of-scope handling? |

Explicitly penalised:

- Technology names with no reason attached
- One agent per requirement — that is a list, not an architecture
- Components that appear on the diagram and are never explained
- "We will use a vector database" with no word about scoping, freshness or
  eviction
- Observability as a heading with nothing measurable under it
- No account of what happens when a component fails
- Length used as a substitute for substance

The judge is told directly that a short, sharply-reasoned document outranks a
long one full of the right vocabulary. Write accordingly.

---

## Submitting

Put your file in `task_1/submissions/` and run:

```bash
python task_1/judge.py
```

It picks up your submission automatically, sends it for review, and writes a
detailed report to `task_1/reports/`. The report is yours — it tells you what
was strong, what was weak, and the questions a reviewer would ask next.

You may run it more than once. Read the report, improve the design, run it
again. That loop is the useful part.
