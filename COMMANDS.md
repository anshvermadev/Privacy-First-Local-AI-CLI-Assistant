# Simple command guide

**PowerShell commands** run before the app opens. **In-app commands** run at the `you@local-ai >` prompt. Enter one line at a time. Slash commands do not run directly in PowerShell.

## 1. Open the app

On Windows, double-click **START.bat**. No activation command is needed.

Or run from the repository folder in PowerShell:

```powershell
.\START.bat
```

For a separate synthetic demo workspace:

```powershell
.\START.bat --data-dir .demo shell
```

## 2. Initialize once

If the app says **setup needed**, type inside the app:

```text
/init --encryption passphrase
```

Enter a passphrase of at least 12 characters, then repeat it. Skip initialization if storage already exists. For a new synthetic-only `.demo` workspace you may use `/init --no-encryption` instead; it stores raw events in plaintext.

## 3. Import the assignment sample

Inside the app:

```text
/sample
```

Expected: **3 accepted** on first import. Repeating this reports duplicates instead of adding the same records again.

Alternatively, from a session launched in the repository folder:

```text
/ingest "src/local_ai/data/mock_events.json"
```

Use `/ingest` with **g**, not `/injest`. Both import commands load the same sample; choose either one.

## 4. Browse, search and explain

```text
/recent
Stripe pricing
/show 1 --explain
marketing roadmap
patient
```

Expected results:

| Search | Expected memory / tier |
|---|---|
| `Stripe pricing` | Rahul's Stripe discussion: **secret** |
| `marketing roadmap` | Q2 roadmap: **confidential** |
| `patient` | Synthetic medical context: **personal**, with detected identifiers redacted |

`/show 1 --explain` refers to result 1 from your latest search/listing. Run it immediately after the result you want to inspect.

## 5. Save your own new input

```text
/remember Asha said project Atlas roadmap launches in December.
Atlas
/show 1 --explain
```

Expected: **NOTE SAVED**, then an Atlas result classified **confidential**. Encrypted storage asks for your passphrase on each save; search does not need it.

## 6. Check policy and workspace

```text
/route --query "Stripe pricing"
/route --query "Stripe pricing" --mode cloud_required
/status
/doctor
```

Default policy: the first route is **local_ai**; requiring cloud returns **blocked**. Neither command sends anything to a cloud service. `/doctor` checks storage, settings and permissions.

## 7. Optional deletion commands

Only run these when you want to delete data. Each asks you to type **DELETE**.

Delete one item: run `/recent`, copy its full ID and replace `ACTUAL_ID`:

```text
/forget --id ACTUAL_ID
```

Delete all memories but retain encryption setup/settings:

```text
/forget --all
```

Hard reset, removing all application state and the encryption key:

```text
/reset
```

Reset closes the app. Initialize again next time. Deleted items can still be visible in earlier on-screen output; `/clear` clears that transcript.

## 8. Scroll and close

- Mouse wheel over output or **PgUp/PgDn**: scroll previous output.
- **Ctrl+Home / Ctrl+End**: jump to oldest/latest output.
- **Up / Down**: recall commands. **Tab**: complete commands.
- **Esc**: cancel an input dialog.

```text
/help
/clear
/exit
```

`/clear` only clears the view. `/exit` closes the app; saved memories remain. Open **START.bat** again and use `/recent` to see them.

See the [README with images](README.md#sample-walkthrough-in-pictures) for examples and the architecture/security answers.
