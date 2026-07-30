# License decision status

## Current status

TumorQuantAI has no repository `LICENSE` file and no declared open-source
license. The source is publicly visible, but copyright protection applies by
default: visibility alone does not grant permission to copy, modify,
redistribute, or create derivative works beyond rights supplied by law or a
separate agreement.

This is a material reuse and contribution blocker. It requires an accountable
owner decision and must not be “fixed” by a contributor selecting a license on
the owner's behalf.

## Decisions that must remain separate

An owner should review at least:

1. **Repository code and documentation** — who owns the copyright and can grant
   permission?
2. **Dependencies and container contents** — are their licenses compatible
   with the intended distribution and use?
3. **HistoPLUS model/code/weights** — gated access and model terms are separate
   from the TumorQuantAI source license; weights are not redistributed here.
4. **Public tutorial dataset** — Zenodo access and its declared CC BY 4.0 terms
   are separate from software; that dataset license cannot be applied to
   repository code or model weights.
5. **Private WSI/clinical data** — institutional governance, consent, privacy,
   and data-use agreements are not replaced by an open-source license.
6. **Contributions** — decide whether a contributor agreement, sign-off, or
   other provenance policy is needed.
7. **Patents, trademarks, and warranty** — obtain appropriate advice for the
   intended project scope.

## Owner checklist

- [ ] Confirm ownership/authority for every repository component.
- [ ] Inventory dependency and container licenses.
- [ ] Review HistoPLUS/LazySlide terms and redistribution boundaries.
- [ ] Confirm the Zenodo record's intended dataset license/reuse statement.
- [ ] Choose a software license with qualified institutional/legal guidance.
- [ ] Add the exact license text and repository metadata in one reviewed PR.
- [ ] Decide whether existing contributions need consent or clarification.
- [ ] Update README, documentation, package/container metadata, and release
      notes without applying the dataset DOI to the software.
- [ ] Document the effective date and treatment of earlier source versions.

Until that checklist is completed, public wording must remain:
“source visible; no reuse permission granted by an absent license.”

This owner license decision is the only expected manual governance action for
the usability overhaul. Future release/tag creation is a separate routine
release action, not unfinished implementation.
