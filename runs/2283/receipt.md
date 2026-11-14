# Receipt: change 2283 (REQ-2283)

> **REHEARSAL.** Rehearsal for the demo. The decisions and the risk statement were written for practice, not by an accountable owner. Not a real sign-off.

- Owner: **Rehearsal Owner**  ·  signed 2026-11-15T00:35:00+02:00  ·  lane **L2**
- Commit: `9df83c38409c` (base `32258fdbee4b`)
- Reading budget: 90 of 228 changed lines
- Bundle: `sha256:2697663dd4e1c01249847cf57a47ab9efff9160b980e4541a71318b53f0e8e6d` over 44 evidence files

## What was checked, and by whom or what
- C1: For a [MessagePackObject] type whose member is a closed generic value type from a referenced assembly, the analyzer no longer throws IndexOutOfRangeException (AD0001). → **timemachine (executed)** (E3)
- C2: For the same input the generator no longer throws (no CS8785) and a GeneratedMessagePackResolver is emitted. → **timemachine (executed)** (E3)

## What was NOT checked, and why
- claim C3: Only struct<T> and record struct<T> from metadata change behaviour; struct, record struct, class<T> and record class<T> from metadata behave exactly as before.: evidence level E1, status refused
- claim C4: No diagnostic that was reported before the change for a type declared in source is lost, moved or changed by the new constructor-level filter.: evidence level E2, status refused
- claim C5: No safety-relevant diagnostic is silently dropped for types the user controls.: evidence level E1, status refused
- claim C6: Diagnostics about the members of a closed generic type from a referenced assembly are reported by the assembly that defines it, so any problem must be fixed there.: evidence level E1, status refused
- claim C7: An unattributed public member of a type defined in a referenced assembly is reported by the project that defines that type.: evidence level E1, status refused
- claim C8: Dropping a diagnostic that has no location in the compilation is required because analyzers are not permitted to report against a location that does not exist.: evidence level E1, status unproven
- claim C9: No live DeclaringSyntaxReferences[0] indexing remains in TypeCollector.cs; the only remaining occurrence is commented out.: evidence level E1, status refused
- claim C10: GetPropertyIdentifierLocation returns null only for properties that have no source declaration (metadata), so no source-declared property loses its diagnostic.: evidence level E1, status unproven
- hunks h4 (X-Ray group g2): no test fails when this code is reverted; owner read it by eye
- the three new tests on the 3.1.x branch: this branch is based on an older commit and the owner has not rebuilt on master yet

## What the AI refused to decide, and the owner's decision
- R-2283-1 (R2-silent-suppression): Do you accept a blanket drop of unlocated diagnostics, or must the drop be limited to symbols that are actually declared in metadata?
  - **Decision:** Require narrowing to metadata symbols: The crash only needs two null-safe lookups. A filter on all 28 call sites can hide a diagnostic nobody planned to hide, and the record case already shows one.
- R-2283-2 (R6-doc-overclaim): Is the documented guarantee true for the packages your users reference, and should it say 'may be reported' instead?
  - **Decision:** Soften to 'may be reported by the defining assembly': A NuGet package built without our analyzer reports nothing, so the doc sentence promises more than we can check.
- R-2283-3 (R1-product-decision): Should a consuming project get at least an informational diagnostic when a referenced generic type has an unattributed public member?
  - **Decision:** Decide later, track in an issue: Whether consumers get an informational hint is a product call for the maintainers. It should not block the crash fix.
- R-2283-4 (R3-unverified-root-cause): Which branch does this fix target, and must the new tests be re-run on that branch before you sign?
  - **Decision:** Re-run on master (3.1.x) first: The branch sits on an older base. I want the three new tests green on the branch we ship from before this merges.

## Residual risk the owner accepts (own words)

> I read the diagnostic filter and the helper by hand. Three tests fail on the old code, so the crash fix is real. What I did not run: the other 3.1.x branch, packages built without the analyzer, and any record shape beyond the three tests. If the filter is wider than it should be, a user could lose a diagnostic and see a clean build, and I accept that until the narrowing lands.

_The AI review is advice with evidence, never the approval. A named human owns this change._
