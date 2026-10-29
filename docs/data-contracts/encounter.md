# encounter

| | |
|---|---|
| **Owner** | Scribe service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | audio_uri expires within 24 h (E6.3). |

## Checks

- every encounter belongs to an appointment
- audio object older than 24 h does not exist
