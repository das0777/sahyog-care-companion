# clinical_note

| | |
|---|---|
| **Owner** | Scribe service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Immutable once signed; edits create a new version (E5.2). |

## Checks

- a signed row is never updated or deleted (trigger)
- (encounter_id, version) unique
- hash present when signed_at is set
