# Corpus

The corpus is the fixed evidence base for the project. It holds one statute and three
real privacy policies, each with a canonical text, a structural index and provenance
metadata.

Nothing in this directory is invented. Every file is either an official government
publication or a policy published by the company concerned, captured on the date
recorded in its metadata.

## Contents

| Slug | Kind | Source | Words |
|---|---|---|---|
| `dpdp-act-2023` | legal | Digital Personal Data Protection Act, 2023, Gazette of India | ~10,600 |
| `google-privacy` | policy | Google Privacy Policy, India locale | ~9,200 |
| `zomato-privacy` | policy | Eternal (formerly Zomato) Privacy Policy | ~7,100 |
| `tiktok-privacy` | policy | TikTok Privacy Policy, rest of world | ~8,700 |

Provenance for the TikTok selection is stored separately:

| File | Purpose |
|---|---|
| `sources/pib-1635206-59-apps-blocked.md` | Press Information Bureau release of 29 June 2020 listing 59 blocked applications, TikTok first |

## Why these three policies

The set is chosen to give the comparison task three different positions relative to
Indian law, not three variations of the same document.

**Google** is an international platform that operates in India and publishes one global
policy with jurisdiction-specific supplements. It is the reference case for a large,
mature policy drafted for many legal regimes at once.

**Eternal (Zomato)** is an Indian consumer platform handling identity, contact, location,
payment and delivery-partner data. It is the reference case for a policy drafted
primarily against Indian expectations.

**TikTok** is item 1 of the 59 applications blocked by the Ministry of Electronics and
Information Technology on 29 June 2020 under section 69A of the Information Technology
Act, 2000. It is the comparison case for a service that does not lawfully operate in
India.

Two caveats must travel with any comparison:

1. The captured TikTok policy is the rest-of-world version, because no India version is
   published while the service is blocked. Scope differences are not evidence of
   non-compliance.
2. Being blocked is a security and sovereignty measure under section 69A, not a finding
   under the DPDP Act, which was enacted three years later. The corpus must not imply
   that the blocking order was a DPDP determination.

## Layout

```text
corpus/
  manifest.json                  index of every source
  README.md
  sources/
    pib-1635206-59-apps-blocked.md
  legal/
    dpdp-act-2023/
      raw/dpdp-act-2023.pdf      original Gazette PDF
      text/dpdp-act-2023.md      raw scrape
      text/content.md            canonical text
      structure/index.json       chapter and section offsets
      metadata.json
  policies/
    <slug>/
      text/privacy-policy.md     raw scrape
      text/content.md            canonical text
      structure/index.json       heading offsets
      metadata.json
```

## Canonical text

Each source has exactly one canonical text, `text/content.md`. Every offset in the
structural index refers to that file. Quotes taken from the index are therefore exact
slices of a file a reviewer can open.

Canonicalisation removes scrape artefacts only: hard-break backslashes, link targets,
image syntax, emphasis markers, inline code fences and table pipes. Wrapped lines are
joined into paragraphs. Heading markers are preserved because they carry structure.

## Structural index

Legal sources use a citation hierarchy:

```text
chapter > section
```

Policy sources use the author's own hierarchy:

```text
h1 > h2 > h3 > h4
```

Every node records `kind`, `label`, `title`, `start`, `end` and, where applicable,
`children`. Offsets are character positions in the canonical text.

### Act structure

The Act index contains 9 chapters and all 44 sections, with no gaps. Each section's
slice begins with its own number and contains its full text.

Section titles are **not** populated. In the Gazette PDF the marginal notes are
interleaved with body text by the extraction layer, so an automatic mapping would be
guesswork. Section numbers, text and offsets are reliable; titles need a curation pass
against the printed Gazette. This is recorded in the index as `title_status:
"unresolved"`.

### Policy structure

Policy indices follow the company's headings. Counts vary because the documents differ
in depth: Google uses many nested headings, Eternal uses a flat list of major sections,
TikTok uses two levels.

## Rebuilding

```bash
uv run python scripts/build_corpus.py
```

The script rewrites canonical text, structural indices and the manifest from the stored
raw files. It does not fetch anything, so rebuilding is deterministic.

## Refreshing a source

Policies change. To refresh one:

1. Re-fetch the source URL into `text/<name>.md`.
2. Update `source_url` and any version note in the metadata if the publisher changed it.
3. Run the build script.
4. Record the new retrieval date in the commit message.

Do not edit `content.md` by hand. It is generated.

## Licensing and use

The DPDP Act is a statute of the Parliament of India and is not subject to copyright.
The privacy policies remain the copyright of their publishers and are stored here for
research and analysis, with source URLs and retrieval dates recorded. They are not
redistributed as standalone works.

## Known gaps

- Section titles for the Act are unresolved.
- Tables are flattened into text; the Schedule to the Act loses its column structure.
- The TikTok policy is rest-of-world, not India-specific.
- No terms of service or EULA is included yet.
- No Indian-language policy is included yet.
- Policy versions are captured once, with no change history.
