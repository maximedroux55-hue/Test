# Standing instructions for the Cowork session

The database and this session do different jobs and neither can do the other's.

The database runs every morning without anyone. It reads the feeds, finds the
rounds, extracts the facts, merges the write-ups, does the arithmetic and keeps
the record. It cannot get past a paywall, cannot read a filing, and takes a
headline at its word. Every error it has made came from that: a ceiling counted
as raised capital, a follow-on called a flotation, a round still being
assembled recorded as closed.

You can read those sources. So the database says what needs checking and you
check it. What you find goes back into one file, where it is applied to every
future run and never overwritten.

## The loop

1. Read **https://maxime-droux.com/digest/verify.json**. It lists the rounds
   worth checking, with the claim as recorded and why each is queued.
2. For each one, find the primary source: the company's own release, the
   filing, or the outlet that reported it first.
3. Check the four things that have actually been wrong:
   - **Has it closed?** Or is it announced, in progress, or subject to
     approval? "Is raising" is not "raised".
   - **Is the label right?** A first listing is an IPO. An already listed
     company selling shares is a Follow-on. A merger with a listed shell is a
     De-SPAC. A purchase is an Acquisition, not a round.
   - **Is the figure money received?** Or a ceiling, a gross, or a target.
     "Up to, assuming no redemptions" is not proceeds.
   - **Did the named investors take part in _this_ round?** Backers of an
     earlier seed are not participants in a Series A.
4. Write what you find into `deeptech-news/corrections.json` in this repo,
   keyed on the company name.

## The file

Set only the fields that are wrong. An empty string clears a value. Always add
`verified` and `verified_source`, including when the round checks out, so it
leaves the queue.

```json
"Prem": {
  "status": "announced",
  "amount_note": "raising, expected to close in Q3",
  "investors": "",
  "verified": "2026-08-04",
  "verified_source": "Bloomberg, 18 June 2026"
}
```

Fields you may set: `company`, `description`, `category`, `stage`, `amount`,
`amount_note`, `status`, `total_raised`, `valuation`, `lead_investor`,
`investors`, `founders`, `spinoff_origin`, `founded`, `employees`,
`use_of_funds`, `customers`, `website`, `location`, `legal_seat`, `verified`,
`verified_source`.

Anything else is rejected by the tests, so a typo fails the build rather than
inventing a column.

## A round the feeds missed

If you find one the database does not have, add it to
`deeptech-news/submissions/rows.json` under `rounds`, with a `source` naming
where it came from. Only `company` is required. If there is an article, put its
address in `submissions/urls.txt` instead and the pipeline will read it itself,
which is better because it fills every field rather than the ones you type.

## Two rules

**Say when you cannot verify something.** An unverifiable round should stay
unverified rather than be marked correct. `verified` means a primary source was
read, not that the claim looked plausible.

**Corrections win over everything.** Nothing in the pipeline can overrule them,
which is what makes them useful and also what makes a wrong one permanent. That
is why `verified_source` is required: it says what was read, so a correction can
be re-checked later rather than taken on trust.
