# Contributing: The Docs-As-We-Go Standard

To maintain high-quality project standards and ensure this codebase remains portfolio-ready at all times, we strictly enforce a **Docs-As-We-Go** policy. 

## The Policy
1. **Never merge undocumented code:** Any feature that is complete enough to be merged to the `main` branch must be immediately documented. We do not retroactively create docs at the end of the project.
2. **Update the `docs/` folder:** Any architectural change or biological shift must be written up in an appropriate markdown file in `docs/`.
3. **Keep `README.md` in sync:** If a new component is built, ensure it is added to the directory structure and overview in the top-level README.
4. **Self-Documenting Code:** Always write clear docstrings and comments directly in the HDL or Python. The external docs should discuss "Why" and "How the system pieces together", while the inline code comments discuss "What the code is doing".

By adhering to this, we can deploy the project to public sites at any moment without needing a "documentation sprint".
