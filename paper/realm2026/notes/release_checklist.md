# REALM 2026 anonymous release checklist

## Artifact and anonymity

- [ ] `python3 paper/realm2026/artifact/validate_artifact.py` passes from a
  clean checkout.
- [ ] Only intended manuscript, analysis, protocol, test, and artifact files
  are staged; archives, raw result rows, and build outputs remain ignored.
- [ ] The bundle contains development-only aggregate evidence and public
  protocol inputs. The sealed final partition, final outcomes, final examples,
  raw traces, credentials, and datasets are absent.
- [ ] `manifest.json` and `checksums.sha256` match after the final source
  freeze.

## ACL review format

- [ ] `main.tex` uses `\usepackage[review]{acl}` and an anonymous author line.
- [ ] The source includes `\usepackage[T1]{fontenc}` and the vendored ACL style
  is the documented official revision.
- [ ] The PDF is A4, has four content pages maximum, and places Limitations
  after the conclusion and before references.
- [ ] `pdffonts` shows embedded Type 1/TrueType/OpenType fonts; `pdfinfo`
  reports A4 media boxes; figures remain readable in grayscale.
- [ ] No author, institution, private repository, local path, or deanonymizing
  URL appears in source, PDF metadata, bibliography, or artifact.

## Scientific/admin checks

- [ ] Every reported number is labeled development-only; no final/test claim is
  introduced by the release process.
- [ ] Citations are complete and every citation key resolves in
  `references.bib`; URLs are not used to reveal author identity.
- [ ] The ethics/admin form is answered, including data provenance, risks of
  financial QA misuse, human-evaluation status, and AI-use disclosure.
- [ ] The paper distinguishes controlled evidence from end-to-end retrieval,
  labels deterministic workflow components accurately, and keeps FinDER
  secondary.

## Licensing

- [ ] Repository license is included or linked in the archive distribution;
  upstream benchmark/provider terms are recorded without redistributing their
  data.
- [ ] Reviewers can inspect source snapshots and hashes without accepting
  provider terms or supplying credentials.
