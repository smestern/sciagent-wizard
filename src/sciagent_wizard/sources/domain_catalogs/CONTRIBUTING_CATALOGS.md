# Contributing Domain Catalogs

Pre-generated domain catalogs let the wizard instantly recommend packages
for common research fields without running live network searches.  Each
domain is a single JSON file in this directory.

## JSON Schema

```json
{
  "domain": "<slug>",
  "display_name": "<Human-Friendly Name>",
  "description": "<1-2 sentence description of the domain>",
  "keywords": ["keyword1", "keyword2", "..."],
  "generated_at": "<ISO 8601 timestamp>",
  "generator_version": "1.0",
  "packages": [
    {
      "name": "<display name>",
      "python_package": "<PyPI name>",
      "description": "<what it does (max 300 chars)>",
      "install_command": "pip install <package>",
      "homepage": "<URL>",
      "repository_url": "<GitHub URL>",
      "relevance_score": 0.85,
      "peer_reviewed": true,
      "citations": 100,
      "downloads": 0,
      "publication_dois": ["10.xxxx/..."],
      "keywords": ["matched", "keywords"]
    }
  ]
}
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `domain` | ✅ | Lowercase slug used as filename (e.g. `electrophysiology`) |
| `display_name` | ✅ | Human-readable title shown to users |
| `description` | ✅ | 1-2 sentences describing what the domain covers |
| `keywords` | ✅ | Terms the LLM uses to match user queries to this catalog |
| `generated_at` | optional | ISO timestamp of when the catalog was generated |
| `generator_version` | optional | Schema version (currently `"1.0"`) |
| `packages` | ✅ | Array of package entries (see below) |

### Package Entry Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Display name of the package |
| `python_package` | recommended | Actual PyPI package name (if different from `name`) |
| `description` | recommended | What the package does (max 300 chars) |
| `install_command` | recommended | e.g. `pip install scipy` |
| `homepage` | optional | Documentation or project URL |
| `repository_url` | optional | GitHub/GitLab URL |
| `relevance_score` | ✅ | Float 0.0–1.0 indicating relevance to the domain |
| `peer_reviewed` | optional | `true` if the package has a peer-reviewed publication |
| `citations` | optional | Approximate citation count |
| `publication_dois` | optional | List of DOI strings |
| `keywords` | optional | Which domain keywords this package matches |

## Adding a New Domain

### Option A: Use the Generation Script

Run the existing discovery pipeline and save results:

```bash
python scripts/generate_domain_catalog.py \
    --domain my_domain \
    --display-name "My Research Domain" \
    --description "Analysis for my research area." \
    --keywords "keyword1,keyword2,keyword3" \
    --queries "keyword1 python package,keyword2 analysis software"
```

Then review and hand-edit the output JSON to:
- Remove irrelevant packages
- Adjust `relevance_score` for packages you know are more/less important
- Add any well-known packages the automated search missed

### Option B: Write by Hand

Copy an existing catalog (e.g. `electrophysiology.json`) and modify it.

### Validation

Validate your catalog before committing:

```bash
python scripts/generate_domain_catalog.py --validate src/sciagent_wizard/sources/domain_catalogs/my_domain.json
```

This checks for:
- Required top-level fields
- Valid `relevance_score` ranges (0–1)
- Each package has a `name`
- Proper JSON structure

## Curation Guidelines

1. **Relevance scores**: The most domain-specific, essential packages
   should score 0.85–0.95.  General-purpose packages (numpy, scipy,
   matplotlib) should score 0.70–0.80.  Niche or less-maintained
   packages should score 0.55–0.70.

2. **Package count**: Aim for 8–15 packages per domain.  Too few and
   the catalog isn't useful; too many and it overwhelms the user.

3. **Always include fundamentals**: numpy, scipy, matplotlib are
   relevant to almost every scientific domain — include them with
   domain-specific descriptions of *why* they're useful.

4. **Peer review**: Mark `peer_reviewed: true` only if the package has
   a published paper (journal or JOSS).  Include the DOI.

5. **Descriptions**: Write descriptions from the perspective of the
   domain, not the package author.  "Signal processing for filtering
   electrophysiology traces" is better than "General-purpose signal
   processing library."

## Regenerating All Catalogs

To re-run live discovery for all existing catalogs:

```bash
python scripts/generate_domain_catalog.py --all
```

This reads each JSON's stored `keywords` and re-runs the discovery
pipeline.  Review the diff before committing.
