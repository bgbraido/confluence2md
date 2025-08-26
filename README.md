# Confluence2MD

Convert Confluence pages to Markdown, including attachments.

## Features

- Fetch Confluence pages by ID or title/space.
- Converts Confluence storage HTML to Markdown using `html2text` or `pandoc`.
- Downloads and rewrites attachment/image links.
- CLI and Streamlit UI.
- Includes unit tests and pre-commit hooks for code quality.

## Project Structure

```
confluence2md/
├── src/
│   └── confluence2md.py       # Main application with CLI and Streamlit UI
├── tests/
│   └── test_main.py           # Unit tests for the application
├── .pre-commit-config.yaml    # Configuration for pre-commit hooks
├── requirements.txt           # List of dependencies
└── README.md                  # Project documentation
```

## Requirements

- Python 3.7+
- See [`requirements.txt`](requirements.txt) for Python dependencies.
- [Pandoc](https://pandoc.org/) (optional, for advanced HTML→Markdown conversion).

## Getting Started

### Prerequisites

Make sure you have Python installed on your machine. You can download it from [python.org](https://www.python.org/downloads/).

### Installation

1. Clone the repository:

   ```sh
   git clone <repository-url>
   cd confluence2md
   ```

2. Install the required packages:

   ```sh
   pip install -r requirements.txt
   ```

3. Set up pre-commit hooks:
   ```sh
   pip install pre-commit
   pre-commit install
   ```

## Usage

### Streamlit UI

Run the Streamlit app:

```sh
streamlit run src/confluence2md.py
```

Fill in credentials and page info interactively in the web interface.

### Programmatic Usage

Use the module programmatically in your Python code:

```python
from confluence2md import init_session, fetch_and_save

# Initialize session with credentials
init_session("https://my-site.atlassian.net/wiki", "me@example.com", "<api-token>")

# Fetch and save a page
fetch_and_save(page_id="12345", out="docs")
```

### CLI (Legacy)

**Note:** CLI usage requires programmatic initialization of credentials first, as environment variables are no longer supported.

Fetch by page ID:

```sh
python src/confluence2md.py --page-id 12345 --out docs
```

Or by title and space:

```sh
python src/confluence2md.py --title "Page Title" --space KEY --out docs
```

#### Options

- `--pandoc`: Use pandoc (must be installed) instead of html2text for HTML→MD conversion.

Example with pandoc:

```sh
python src/confluence2md.py --page-id 12345 --out docs --pandoc
```

### Running Tests

To run the unit tests, use:

```sh
python -m unittest discover -s tests
```

or if using pytest:

```sh
pytest tests
```

## Output

- Markdown file saved to output directory.
- Attachments downloaded to `attachments/` subdirectory with clean, readable paths.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.
