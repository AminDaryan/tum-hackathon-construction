/** German for: Risks, issues, the side panel, validation, documents and exports. */
export const review = {
  // Review count explanations
  'Unreviewed findings across the bills in the last project validation. Counts all reviewers, regardless of workspace filters.':
    'Noch nicht geprüfte Befunde aller Leistungsverzeichnisse aus der letzten Projektprüfung. Gilt für alle Prüfenden, unabhängig von den Filtern im Arbeitsbereich.',
  'Unreviewed findings in the selected validation run of this file. Counts all reviewers, regardless of risk list filters.':
    'Noch nicht geprüfte Befunde im ausgewählten Prüflauf dieser Datei. Gilt für alle Prüfenden, unabhängig von den Filtern der Risikoliste.',
  'Risks awaiting clarification, within the current filters and assignee selection. A risk may group several findings.':
    'Risiken, die auf Klärung warten, unter Berücksichtigung der aktuellen Filter und Zuständigkeitsauswahl. Ein Risiko kann mehrere Befunde zusammenfassen.',
  // Common words
  'All': 'Alle',
  'Any': 'Beliebig',
  'None': 'Keine',
  'Open': 'Offen',
  'Quantity': 'Menge',
  'History': 'Verlauf',
  'issue': 'Befund',
  'issues': 'Befunde',
  'finding': 'Befund',
  'findings': 'Befunde',
  'detector': 'Prüfregel',
  'detectors': 'Prüfregeln',

  // Risks: status, method, certainty, harm, category, money
  'In review': 'In Klärung',
  'Approved': 'Bestätigt',
  'Rejected': 'Abgelehnt',
  'Rule': 'Regel',
  'Text check': 'Textprüfung',
  'Statistics': 'Statistik',
  'Language model': 'Sprachmodell',
  'Confirmed': 'Bestätigt',
  'Suspected': 'Vermutet',
  'Text signal': 'Textsignal',
  'Unclear': 'Unklar',
  'A rule shows it in the bill.': 'Eine Regel weist es im Leistungsverzeichnis nach.',
  'A comparison makes it likely; the bill alone cannot prove it.':
    'Ein Vergleich macht es wahrscheinlich; das Leistungsverzeichnis allein kann es nicht belegen.',
  'The wording points to it.': 'Der Wortlaut deutet darauf hin.',
  'The information at hand cannot decide it.': 'Mit den vorliegenden Angaben lässt es sich nicht entscheiden.',
  'Money': 'Kosten',
  'Contract': 'Vertrag',
  'Schedule': 'Termine',
  'Safety': 'Sicherheit',
  'Data quality': 'Datenqualität',
  'The positions concerned are a large share of the bill': 'Die betroffenen Positionen machen einen großen Anteil des Leistungsverzeichnisses aus',
  'The positions concerned are a medium share of the bill': 'Die betroffenen Positionen machen einen mittleren Anteil des Leistungsverzeichnisses aus',
  'The positions concerned are a small share of the bill': 'Die betroffenen Positionen machen einen kleinen Anteil des Leistungsverzeichnisses aus',
  'Not known': 'Nicht bekannt',
  '{low} to {high} (estimate)': '{low} bis {high} (Schätzung)',
  '{amount} (estimate)': '{amount} (Schätzung)',
  'Comparison: {amount}': 'Vergleichswert: {amount}',
  'Not a loss: the price may be right.': 'Kein Verlust: Der Preis kann richtig sein.',
  '{list} and {count} more': '{list} und {count} weitere',
  'With an amount': 'Mit Betrag',
  '1,000 or more': 'Ab 1.000',
  '10,000 or more': 'Ab 10.000',

  // Issues
  'No events recorded yet.': 'Noch keine Ereignisse erfasst.',
  '{time} by {actor}': '{time} von {actor}',
  'Product': 'Produkt',
  'Sum': 'Summe',
  'Difference': 'Differenz',
  'Percentage': 'Prozentsatz',
  'Comparison': 'Vergleich',
  '{operation} of {count} terms': '{operation} aus {count} Termen',
  '{count} more terms not listed': '{count} weitere Terme nicht aufgeführt',
  '{count} more term not listed': '{count} weiterer Term nicht aufgeführt',
  'further terms not listed': 'weitere Terme nicht aufgeführt',
  'Exact result': 'Exaktes Ergebnis',
  'Rounded ({rounding})': 'Gerundet ({rounding})',
  'Reported': 'Angegeben',
  'Difference (reported − expected)': 'Differenz (angegeben − erwartet)',
  'Allowed difference': 'Zulässige Abweichung',
  'and {count} more': 'und {count} weitere',
  'Amount = reported − recomputed: a positive amount means the document states more than the recomputed value. It shows that the figures disagree, not which one is wrong.':
    'Betrag = angegeben − nachgerechnet: Ein positiver Betrag bedeutet, dass das Dokument mehr ausweist als der nachgerechnete Wert. Er zeigt, dass die Zahlen nicht übereinstimmen, nicht welche falsch ist.',
  'The value of rows that look duplicated: it would be counted twice if both rows stay in the total.':
    'Der Wert scheinbar doppelter Zeilen: Er würde doppelt gezählt, wenn beide Zeilen in der Summe bleiben.',
  'Quantity × (unit price − reference unit price), after any item discount. Reported and recomputed below are unit prices, not line totals. This is a comparison scenario, not a confirmed loss or a market-price estimate.':
    'Menge × (Einheitspreis − Vergleichs-Einheitspreis), nach einem etwaigen Positionsnachlass. Angegeben und nachgerechnet sind unten Einheitspreise, keine Gesamtpreise. Dies ist ein Vergleichsszenario, kein bestätigter Verlust und keine Marktpreisschätzung.',
  '(currency unknown)': '(Währung unbekannt)',
  'Amount': 'Betrag',
  'Recomputed': 'Nachgerechnet',
  'Basis': 'Grundlage',
  'The detector attached no structured evidence.': 'Die Prüfregel hat keine strukturierten Nachweise angehängt.',
  'Cells': 'Zellen',
  'Extraction confidence': 'Erkennungssicherheit',
  'Lowest confidence the extraction engine reported for the cells involved (0 to 1).':
    'Niedrigste Sicherheit, die die Texterkennung für die betroffenen Zellen gemeldet hat (0 bis 1).',
  'Anomaly score': 'Anomaliewert',
  'Threshold': 'Schwellenwert',
  'Method': 'Methode',
  'Interpretation': 'Bedeutung',
  'Calibration': 'Kalibrierung',
  'Calibrated against {reference}': 'Kalibriert anhand von {reference}',
  'Not calibrated: a raw score, not a probability of error.':
    'Nicht kalibriert: ein Rohwert, keine Fehlerwahrscheinlichkeit.',

  // Validation
  'Validation run': 'Prüflauf',
  '{run} (latest)': '{run} (neuester)',
  'Run {id}': 'Prüflauf {id}',
  'The validation run failed before detectors could finish. See the run details for warnings.':
    'Der Prüflauf ist fehlgeschlagen, bevor die Prüfregeln abschließen konnten. Warnungen finden Sie in den Details des Prüflaufs.',
  'Validation run finished with {issues}. {detectors} completed, {skipped} skipped, {failed} failed, {stopped} stopped.':
    'Prüflauf abgeschlossen: {issues}. {detectors} ausgeführt, {skipped} übersprungen, {failed} fehlgeschlagen, {stopped} abgebrochen.',
  'Validation run finished with {issues}. {detectors} completed, {skipped} skipped, {failed} failed.':
    'Prüflauf abgeschlossen: {issues}. {detectors} ausgeführt, {skipped} übersprungen, {failed} fehlgeschlagen.',
  'Validation run queued. It starts when the server is ready; this page updates when it has finished.':
    'Prüflauf eingereiht. Er startet, sobald der Server bereit ist; diese Seite aktualisiert sich, wenn er abgeschlossen ist.',
  'Validation run in progress on the server. This page updates when it has finished.':
    'Der Prüflauf läuft auf dem Server. Diese Seite aktualisiert sich, wenn er abgeschlossen ist.',
  'Running validation. Detectors run on the server; this page updates when the run has finished.':
    'Prüfung läuft. Die Prüfregeln laufen auf dem Server; diese Seite aktualisiert sich, wenn der Prüflauf abgeschlossen ist.',
  'The progress of the validation run could not be followed':
    'Der Fortschritt des Prüflaufs konnte nicht verfolgt werden',
  'The validation run could not be completed': 'Der Prüflauf konnte nicht abgeschlossen werden',
  'The review can be finished only after the validation run completed.':
    'Die Durchsicht kann erst abgeschlossen werden, wenn der Prüflauf beendet ist.',
  '{findings} still pending review.': '{findings} noch nicht durchgesehen.',
  'Run review marked as finished.': 'Durchsicht des Prüflaufs als abgeschlossen markiert.',
  'Run review reopened.': 'Durchsicht des Prüflaufs wieder geöffnet.',
  'Current status': 'Aktueller Status',
  'since {time}': 'seit {time}',
  '{findings} pending review': '{findings} nicht durchgesehen',
  'Reopen review': 'Durchsicht wieder öffnen',
  'Finish review': 'Durchsicht abschließen',
  'The run review status was not updated': 'Der Status der Durchsicht wurde nicht aktualisiert',

  // Documents
  'Column': 'Spalte',
  '“{name}” is a legacy Word file (.doc). Save it as .docx (Word: File > Save As > Word Document) or as PDF, and upload that.':
    '„{name}“ ist eine ältere Word-Datei (.doc). Speichern Sie sie als .docx (Word: Datei > Speichern unter > Word-Dokument) oder als PDF und laden Sie diese hoch.',
  '“{name}” is not a supported file type. Supported: {formats}.': '„{name}“ hat keinen unterstützten Dateityp. Unterstützt: {formats}.',
  'Needs review': 'Prüfung nötig',
  'Note': 'Notiz',

  // Exports
  'Download Excel': 'Excel herunterladen',
  'Preparing the Excel file…': 'Excel-Datei wird vorbereitet …',
  'Downloaded {file} ({size}).': '{file} heruntergeladen ({size}).',
  'The Excel file could not be downloaded': 'Die Excel-Datei konnte nicht heruntergeladen werden',
  'Download workbook (Excel)': 'Arbeitsmappe herunterladen (Excel)',
  'One sheet per extracted table with its source page or row, a sheet with every issue, and the extraction report. Numbers stay numbers.':
    'Ein Blatt je eingelesener Tabelle mit Quellseite oder -zeile, ein Blatt mit allen Befunden und der Einlesebericht. Zahlen bleiben Zahlen.',
  'Download issues (CSV)': 'Befunde herunterladen (CSV)',
  'One row per issue: location, observed and expected values, explanation and review status. Opens in any spreadsheet application.':
    'Eine Zeile je Befund: Fundstelle, vorgefundene und erwartete Werte, Erläuterung und Prüfstatus. Lässt sich in jeder Tabellenkalkulation öffnen.',
  'Download tables (ZIP)': 'Tabellen herunterladen (ZIP)',
  'The issues CSV, one CSV per extracted table with its source row numbers, and a manifest.':
    'Die Befund-CSV, eine CSV je eingelesener Tabelle mit den Quellzeilennummern und ein Manifest.',
  'Download JSON export': 'JSON-Export herunterladen',
  'The canonical dataset revision, the validation run with its plan and detector reports, the detector specifications and every issue with its current review status.':
    'Die kanonische Revision des Datensatzes, der Prüflauf mit Plan und Berichten der Prüfregeln, die Spezifikationen der Prüfregeln und alle Befunde mit ihrem aktuellen Prüfstatus.',
  'Download questions document (Markdown)': 'Fragenkatalog herunterladen (Markdown)',
  'A ready-to-send questions list for findings marked Needs more information, with location and context per finding.':
    'Eine versandfertige Fragenliste zu den Befunden mit dem Status „Weitere Informationen nötig“, mit Fundstelle und Kontext je Befund.',
  'Preparing the export…': 'Export wird vorbereitet …',
  'Export downloaded: {file} ({size}).': 'Export heruntergeladen: {file} ({size}).',
  'The export could not be downloaded': 'Der Export konnte nicht heruntergeladen werden',
};
