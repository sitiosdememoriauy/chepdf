*Leer en [Español](README.md).*

# 📄 Che PDF

**Che PDF** is an advanced, high-performance document indexing and search engine. It is specifically designed to process, analyze, and search for text within massive repositories of historical PDF files (tested on volumes up to 4TB).

This application was developed by **sitiosdememoria.uy** with the aim of facilitating the analysis and research of large document volumes. It is released under a free software license that allows its use, study, distribution, and modification, as part of the project's commitment to the struggles for memory, truth, and justice.

## ✨ Main Features

* **Ultra-fast Search (FTS5):** Uses SQLite FTS5 to perform instant searches across millions of words, supporting advanced syntax (exact phrases, AND, OR, NOT).
* **Historical Metadata Management:** Automatically extracts the document's year using three configurable methods: file name, parent folder name, or internal PDF metadata.
* **Dynamic Filters:** Allows narrowing down searches by precise year ranges and specific folders using an intuitive interface.
* **Direct Reading:** Clicking on a result opens the PDF in the operating system's default web browser exactly on the matching page and with the search term highlighted.
* **Safety Limits:** Integrates a configurable emergency brake (default 10,000 results) to prevent memory crashes when searching for very common terms in massive archives.
* **User-Friendly Graphical Interface (GUI):** Built in Python with Flet (Flutter), offering a dark, modern, and easy-to-use environment for non-technical users.

## 🛠️ System Requirements and Technologies

The source code is written in **Python 3**. The main dependencies are:
* `flet==0.28.3` (Note: This specific and stable version of the original architecture is used to ensure hardware compatibility and avoid screen flickering bugs present in later versions).
* `PyMuPDF` (fitz) for document processing.
* `sqlite3` (native to Python).

## 🚀 Installation and Execution from Source Code

If you want to run the program from its source code or contribute to its development:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sitiosdememoriauy/chepdf.git
   cd chepdf
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   ```

   **On Windows:**
   ```bash
   .venv\Scripts\activate
   ```

   **On Linux/Mac:**
   ```bash
   source .venv/bin/activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install flet==0.28.3 PyMuPDF
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

## 📦 Compilation

To distribute the program to end users without them needing to install Python, you can compile it using the Flet packager. Run the following command in the root of the project:

**Windows:**
```bash
flet pack app.py --name "Che PDF" --icon "_internal/assets/icono_che.ico" --add-data "_internal/assets;_internal/assets"
```

**Linux:**
```bash
flet pack app.py --name "che-pdf" --icon "_internal/assets/icono_che.png" --add-data "_internal/assets:_internal/assets"
```

*This will generate a `dist` folder containing the final executable and the resources folder. You can compress this folder into a `.zip` or a `.tar.gz` file for distribution.*

## 📖 Basic Usage Guide

1. **Initial Configuration:** Go to the 'Configuration' tab and select the method to deduce the historical year (by file name, folder name, or metadata).
2. **Indexing:** Click the folder button in the side menu to add your PDF directory. The system will scan and save the text in the internal database.
3. **Filters:** Use the sidebar to define a year range or select specific folders.
4. **Search:** Enter your term in the top bar. If there are too many results, the system will ask you to refine the filters.
5. **Reading:** Click on any result to open the original PDF on the exact page.

## 🤝 <img src="http://sitiosdememoria.uy/sites/default/files/inline-images/Flag_of_Uruguay.svg" height="20"> Support the Project

**Che PDF** is and will always be a free and open-source tool. Your voluntary contribution helps us maintain our infrastructure, develop new tools, and continue with our research work.

If you find the tool useful, please consider making a solidarity contribution:
💖 **Donate via Ko-fi:** https://ko-fi.com/sitiosdememoriauy

## 👨‍💻 Authors

* **Rodrigo Barbano and Mariana Risso** - Researchers and developers.
* Project powered by [sitiosdememoria.uy](https://sitiosdememoria.uy).

## 📄 License

This project is licensed under the **GNU GPLv3** License. You are free to use, study, share, and modify this software for any purpose, as long as derivative works maintain the same open license.
