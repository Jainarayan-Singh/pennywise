# Quick add: the expense pipeline

The model never decides what is saved. It returns phrases and proposals; the application parses, matches, validates and asks.
Nothing becomes a transaction until the user confirms the review, and the draft id makes that confirmation idempotent.

| Stage | Module | Responsibility |
|---|---|---|
| Extract | `expense_intent.py` | One structured model call per message. The model copies phrases (amount, date, category hint, merchant, account hint) and may propose a category or account **name copied from the user's own lists**. Amounts, currencies and dates are parsed by fixed rules (`parse_spoken_amount`, `resolve_date_phrase`). |
| Resolve | `expense_resolution.py` | Type, category, account and payment method, from explicit words first, then the user's data (below). |
| Validate | `expense_validation.py` | Re-checks every value with the rules manual entry uses, and against the user's own active categories and accounts. Invalid values are removed, never repaired by guessing. |
| Clarify | `expense_clarification.py` | Decides ready or not, and the single next question, with the user's own options to tap. |
| Orchestrate and save | `draft_service.py` | Draft lifecycle, merging each answer into the same draft, and `confirm_draft`. |

## Field states

`known` said by the user (or a fixed rule from what they said) · `inferred` a suggestion shown for confirmation, with the reason · `missing` required and absent · `ambiguous` several accounts fit, or the user has to choose.

## Required, and asked about

Amount, type and date are required. If amount and date are both missing the question is combined ("How much was it, and on which date?"). A repeated question says what it still needs. Direct answers (a number, "expense", "yesterday", a tapped option) are parsed locally without an AI call.

Category and account are optional in the data model. Each is asked about **once**, only when it could not be resolved, with the user's own choices and a way to skip: accounts only when the user has two or more (or named an account they do not have); categories only of the right kind, ordered by how often they are used.

## Resolution rules (in order)

* **Type:** the model's reading; otherwise the wording ("paid", "received", "salary"); otherwise a category that only exists as income or expense. Never defaulted.
* **Category:** the user's own category name in the text (known) → a name the model proposed that exactly matches an active category of the right kind → synonyms for the stated purpose → the category every one of the last five payments to the same merchant used → synonyms anywhere in the text. Archived categories and categories of the wrong kind are never used.
* **Account:** an account named in the text, by full name or by a distinctive word ("HDFC" for "HDFC Savings"). One match is known; several matches are ambiguous and only those are offered. An account named but not owned is asked about, never replaced. Without a mention: the only account of the type the payment method points at (cash → a cash account) → the user's only account → the account every recent payment to the same merchant (or in the same category, at least two) used → an established habit (at least five of the last twenty payments, and 80% or more of them, used that account). An even split is not a habit. Otherwise it stays unresolved and, with two or more accounts, is asked about. The most recently created account is never assumed.
* **Payment method:** the model's reading, or from a cash or card account.
* **Currency:** the currency stated, else the chosen account's, else the user's preferred currency.
* **Date:** only from the user's words, in the user's timezone. A date that cannot be read, is ambiguous ("last month") or is in the future is asked about. There is no default date.

## What the model is sent

The user's message, and the **names** of their active categories and accounts. No amounts, balances, dates of earlier transactions or merchants. Every proposal is checked in code.
