from pathlib import Path

collect_path = Path(".github/workflows/collect.yml")
collect_text = collect_path.read_text(encoding="utf-8")

old_collect = """      - name: Compile LaTeX CVs
        uses: xu-cheng/latex-action@v3
        with:
          root_file: output/*.tex
          args: -pdf -file-line-error -halt-on-error -interaction=nonstopmode -outdir=output

      - name: Verify generated CV PDFs
        run: |
          echo "Generated files in output/:"
          ls -la output/ || echo "output dir not found"
          echo "PDFs found:"
          find output -maxdepth 1 -name "*.pdf" -print || echo "No PDFs found"
      - name: Run Pipeline (Phase 2 - Finalize Assets & Notify)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          MY_TELEGRAM_CHAT_ID: ${{ secrets.MY_TELEGRAM_CHAT_ID }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_SENDER_ADDRESS: ${{ secrets.GMAIL_SENDER_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: python -m src.pipeline --phase finalize_assets
# trigger update
# trigger update
# trigger update
# trigger update"""

new_collect = """      - name: Compile LaTeX CVs
        if: ${{ hashFiles('output/*.tex') != '' }}
        uses: xu-cheng/latex-action@v3
        with:
          root_file: output/*.tex
          args: -pdf -file-line-error -halt-on-error -interaction=nonstopmode -outdir=output

      - name: Verify generated CV PDFs
        run: |
          echo "Generated files in output/:"
          ls -la output/ || echo "output dir not found"
          echo "PDFs found:"
          find output -maxdepth 1 -name "*.pdf" -print || echo "No PDFs found"

      - name: Run Pipeline (Phase 2 - Finalize Assets & Notify)
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          MY_TELEGRAM_CHAT_ID: ${{ secrets.MY_TELEGRAM_CHAT_ID }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_SENDER_ADDRESS: ${{ secrets.GMAIL_SENDER_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: python -m src.pipeline --phase finalize_assets
"""

if old_collect in collect_text:
    collect_path.write_text(collect_text.replace(old_collect, new_collect), encoding="utf-8", newline="\n")
    print("Updated collect.yml")
else:
    print("Pattern not found in collect.yml")

dispatch_path = Path(".github/workflows/dispatch.yml")
dispatch_text = dispatch_path.read_text(encoding="utf-8")

old_dispatch = """      - name: Execute Dispatcher
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: python -c "from src.dispatchers.gmail import dispatch_approved_applications; dispatch_approved_applications()\""""

new_dispatch = """      - name: Execute Dispatcher
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_SENDER_ADDRESS: ${{ secrets.GMAIL_SENDER_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
        run: python -c "from src.dispatchers.gmail import dispatch_approved_applications; dispatch_approved_applications()\""""

if old_dispatch in dispatch_text:
    dispatch_path.write_text(dispatch_text.replace(old_dispatch, new_dispatch), encoding="utf-8", newline="\n")
    print("Updated dispatch.yml")
else:
    print("Pattern not found in dispatch.yml")
