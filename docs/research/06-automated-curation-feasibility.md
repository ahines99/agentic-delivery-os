# Automated curation feasibility: rights and executable environments

Research date: 2026-09-28. Scope: the existing 36 metadata candidates, not task qualification.
All 36 remain UNQUALIFIED. This review used primary-source documentation, package metadata,
license files, and static packaging metadata only. It did not fetch task statements, patches,
hidden test IDs, reference solutions or sealed answers; install or execute upstream code;
make model calls; or change the candidate catalog. Parsing a packaging file with `ast` below
did not import it or run its build hooks.

## Findings

The current fixed collector is not a qualified environment for these historical repositories.
Pytest itself conflicts with the trusted pytest used by the collector; Sphinx has an absent
dependency stack and fixture requirements; SymPy needs absent dependencies and historical
runner compatibility work. Separately, SWE-bench's MIT declaration is positive licensing
evidence, but the inspected sources do not unambiguously resolve every dataset/issue/content
usage scope. Neither agent consensus nor a successful install can close those gaps.

The local metadata projection contains the following installation-version labels. These are
not dependency locks or proof of Python compatibility. The pinned dataset card describes
`created_at` as PR creation time, not the original issue timestamp.

| Repository | Candidates | Version labels in the metadata | PR creation range |
| --- | --- | --- | --- |
| pytest-dev/pytest | 12 | 4.5, 4.6, 5.0, 5.1, 5.2, 5.4, 7.2 | 2019-05-14 to 2022-10-08 |
| sphinx-doc/sphinx | 12 | 3.0, 3.1, 5.0, 5.1, 5.2, 7.1, 7.2 | 2020-04-08 to 2023-07-24 |
| sympy/sympy | 12 | 1.0, 1.1 | 2016-09-15 to 2017-11-28 |

The private `.local/candidate-issue-links.json` metadata research contains 36 complete link
queries, 17 candidates with one or more linked issues and 19 without returned issue links.
That is linkage evidence, not 17 eligible tasks. It does not establish historical issue text,
requirements clarity, rights, risk, oracle quality or family grouping. No linked issue bodies
were opened here. Missing links must not be replaced with invented issue URLs.

## What the licensing sources establish

| Evidence | Supported conclusion | Remaining uncertainty |
| --- | --- | --- |
| Official SWE-bench repository describes code and data and declares MIT; its license names the project authors and grants permissions for software and associated documentation | MIT is a real affirmative project declaration, not an inference from popularity | The text does not separately enumerate the hosted Verified dataset, copied issue text, third-party files or downstream model processing; this review cannot decide that all such material falls within the grant |
| Verified card at the exact catalog revision has no `license` metadata or separate license section | The card's license declaration is absent | Absence is not evidence that the dataset is prohibited, public domain, or necessarily outside the repository's MIT declaration |
| Pinned upstream project license evidence already exists for pytest MIT, Sphinx BSD-2-Clause and SymPy BSD-3-Clause | Relevant permissive code-license provenance is available | File-specific/embedded exceptions and provenance of copied issue or dataset material require their own scope review |
| Public GitHub issue links and current Terms sections D.5/D.6 | The Terms distinguish public visibility/forking and contributions under a repository license | Public access alone does not settle this project's off-platform dataset redistribution/model-processing rights; current wording also does not establish the terms applicable when old content was contributed |

Sources: [official SWE-bench README](https://github.com/SWE-bench/SWE-bench/blob/main/README.md),
[MIT license](https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/LICENSE),
[pinned Verified card](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/blob/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/README.md),
[Hugging Face card metadata documentation](https://huggingface.co/docs/hub/datasets-cards),
and [GitHub user-generated-content terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#d-user-generated-content),
accessed 2026-09-28. The card was fetched as README bytes only, without dataset rows.
Card SHA-256: `6edb58b1b2c44ce858426c4ebc90077827713b75cebc243661e4433c81fd57f5`.
Observed MIT file SHA-256: `2bd2e08df7147f67a69b42c10efae09bd4bf119df397371036187d5dd1b02f57`;
its URL is moving `main`, so retain that digest or pin a revision for later qualification.

The correct current result is unresolved scope, not a categorical claim that the dataset is
MIT-covered or unlicensed. Before admission, an authorized provenance record must explain which
grant covers repository files, dataset compilation, issue material, intended model processing
and any redistribution, with applicable notices retained. A documented applicable grant may
resolve this without new human benchmark reviewers. If scope remains uncertain, keep `rights`
PENDING and use an alternative authorized task; an agent cannot manufacture legal clearance.
This research did not change rights decisions or contact a rights holder.

## Concrete runtime mismatches

The inspected [Dockerfile](../../infra/docker/sandbox.Dockerfile) installs Python 3.12 and
pytest 9.1.1, iniconfig 2.3.0, packaging 26.3, pluggy 1.6.0 and pygments 2.21.0. It does not
install general historical-project or testing extras. The image-owned
[collector](../../infra/docker/collector.py) imports trusted pytest from `/usr/local/lib`,
appends `/workspace` after installed packages, ignores repository pytest configuration,
disables conftest and plugin autoload, and uses importlib collection. Those are deliberate
controls, not evidence that an upstream suite behaves equivalently under them.

| Repository | Metadata evidence | Concrete preparation needed |
| --- | --- | --- |
| pytest | Representative exact-base `setup.cfg` uses `src` layout and requires attrs/py plus testing extras. Published 4.5.0 and 5.4.0 require pluggy below 1.0; the collector has 1.6.0. Upstream development guidance installs the editable package with testing extras and uses pytester | Separate the trusted observation/control boundary from the candidate pytest implementation. The collector currently imports its fixed pytest before adding the workspace; simply running historical tests may test the installed tool instead of candidate code. Adding `/workspace` also does not install a `src` layout. Replacing trusted pytest with candidate code invalidates the existing trust assumption. Qualify a versioned subprocess/external observation design with exact candidate import provenance and adversarial evidence checks |
| Sphinx | Representative exact-base packaging requires Jinja2, docutils below 0.18, six sphinxcontrib packages and other dependencies absent from the image; test extras include pytest-cov, html5lib and Cython. Sphinx's testing API uses pytest fixtures/plugins | Prepare exact-base dependency bundles and a pinned image, including required toolchain/assets only. Preserve qualified fixture behavior with an explicit trusted profile; do not blindly re-enable arbitrary conftest/plugin execution or treat missing fixtures as skipped success. Validate approved tests against the original environment semantics |
| SymPy | Representative 2016 base metadata requires mpmath at least 0.19 and lists Python through 3.5; published 1.0/1.1 metadata lacks useful `requires_dist` constraints. Current upstream docs describe a native runner and optional pytest support | Supply a reproducible mpmath/toolchain bundle and establish compatibility for each exact old base. Current docs do not certify 2016/2017 code under Python 3.12. The current command profile admits only a narrow pytest invocation, not SymPy's native runner. Qualify a faithful supported adapter or exclude incompatible tasks; do not silently modernize historical code |

Primary metadata sources:

- [Exact pytest base setup.cfg](https://raw.githubusercontent.com/pytest-dev/pytest/aa55975c7d3f6c9f6d7f68accc41bb7cadf0eb9a/setup.cfg),
  [pytest 4.5.0 release metadata](https://pypi.org/pypi/pytest/4.5.0/json),
  [5.4.0 metadata](https://pypi.org/pypi/pytest/5.4.0/json), and
  [7.2 development documentation](https://docs.pytest.org/en/7.2.x/contributing.html).
- [Exact Sphinx base packaging metadata](https://raw.githubusercontent.com/sphinx-doc/sphinx/31eba1a76dd485dc633cae48227b46879eda5df4/setup.py),
  [Sphinx 3.0.0 metadata](https://pypi.org/pypi/Sphinx/3.0.0/json),
  [5.0.0 metadata](https://pypi.org/pypi/Sphinx/5.0.0/json),
  [7.2.0 metadata](https://pypi.org/pypi/Sphinx/7.2.0/json), and
  [official fixture/plugin API](https://www.sphinx-doc.org/en/master/extdev/testing.html).
- [Exact SymPy base packaging metadata](https://raw.githubusercontent.com/sympy/sympy/360290c4c401e386db60723ddb0109ed499c9f6e/setup.py),
  [1.0 release metadata](https://pypi.org/pypi/sympy/1.0/json),
  [1.1 metadata](https://pypi.org/pypi/sympy/1.1/json), and
  [current upstream dependency/runner documentation](https://docs.sympy.org/dev/contributing/dependencies.html).

These are representative exact-base checks plus released-package metadata, not a dependency audit
of all 36 bases. Python lower bounds without an upper bound do not prove later interpreter
compatibility. In particular, the representative Sphinx base's docutils bound differs from its
subsequent 5.0.0 release metadata: version labels cannot replace exact-base reconstruction.

The current limits also require an admission preflight: 1,000 text files, 256 KiB per file,
8 MiB aggregate snapshot, 1,000 collected tests, 1 MiB report, 256 MiB container memory and
64 PIDs. No complete historical tree/suite was fetched or measured in this review, so no claim
is made that a specific candidate exceeds them. Do not truncate snapshots or omit required
regressions to fit. A compatible partitioned runner or an explicitly versioned, requalified
resource profile may be necessary.

Upstream SWE-bench's [harness documentation](https://www.swebench.com/SWE-bench/reference/harness/)
describes task Docker environments and substantially larger host resource recommendations. It
also warns that result reuse is keyed by run/instance, not a changed prediction diff. Importing
that harness is not a shortcut to this project's evidence authority: qualify its profiles,
use fresh candidate-bound execution identities, and never count cached results as a new run.
Its host recommendations are not measured requirements for these 36 tasks.

## Bounded next work

1. Resolve authoritative rights scope and historical issue linkage in protected provenance records;
   no task-body or answer access is needed merely to inventory grants and metadata. Keep unresolved
   decisions explicit rather than treating a permissive code license as universal authorization.
2. Build an exact-base packaging inventory for development candidates first. Pin supported Python,
   OS, architecture, build tooling, dependency wheels/hashes and license notices; retain preparation
   logs. Networked preparation belongs in a separate credential-free preparation boundary, not in
   the offline candidate sandbox. No such preparation was executed here.
3. Design and qualify the pytest-under-test boundary before attempting those candidates. For other
   repositories, define image-owned fixture/plugin profiles and import provenance without changing
   frozen acceptance semantics. Re-run collector forgery, early-exit, resource and cleanup tests.
4. Preflight complete snapshot/suite/resource requirements. The bounded qualification v1 expects
   one all-fail-to-pass acceptance profile and one stable regression profile, three baseline and
   three reference repetitions per profile: 12 fresh execution receipts. Mixed suites or multiple
   profiles require a supported schema extension, not fabricated outcomes or selective omission.
5. Only after those gates, perform protected oracle execution and two isolated semantic agent
   reviews under [ADR-007](../adr/ADR-007-automated-benchmark-qualification.md). Keep validation and
   sealed-test answers outside development contexts. Preserve minimum 30/target 36, three
   repositories, family grouping, finite budgets and unsuccessful/unresolved denominators.

Metadata-only preparation remains useful, but this catalog is not ready for unattended historical
qualification today. No baseline, reference execution, independent review or legal clearance was
produced by this research, and no task was admitted.
