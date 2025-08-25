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
│   └── main.py                # Main entry point of the application
├── tests/
│   └── test_main.py           # Unit tests for the application
├── confluence2md.py           # CLI and Streamlit UI
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

### CLI

Set your Confluence credentials as environment variables:

```sh
export CONFLUENCE_URL="https://your-domain.atlassian.net/wiki"
export CONFLUENCE_USER="you@example.com"
export CONFLUENCE_API_TOKEN="api-token"
```

Fetch by page ID:

```sh
python confluence2md.py --page-id 12345 --out docs
```

Or by title and space:

```sh
python confluence2md.py --title "Page Title" --space KEY --out docs
```

Use `--pandoc` to convert HTML to Markdown via Pandoc:

```sh
python confluence2md.py --page-id 12345 --out docs --pandoc
```

### Streamlit UI

Install requirements:

```sh
pip install -r requirements.txt
```

Run the Streamlit app:

```sh
streamlit run confluence2md.py
```

Fill in credentials and page info interactively.

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
- Attachments downloaded to a subdirectory.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.
