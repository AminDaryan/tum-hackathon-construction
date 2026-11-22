/** German for: Shared components, vocabulary and services. */
export const shared = {
  // Common words
  Close: 'Schließen',
  Retry: 'Erneut versuchen',
  Previous: 'Zurück',
  Next: 'Weiter',
  Copied: 'Kopiert',
  None: 'Keine',
  Unknown: 'Unbekannt',
  Quantity: 'Menge',
  Unit: 'Einheit',
  Risk: 'Risiko',

  // Components
  'No matches': 'Keine Treffer',
  'The browser did not allow copying.': 'Der Browser hat das Kopieren nicht erlaubt.',
  '{caption}. Press Enter on a row to open it.': '{caption}. Drücken Sie die Eingabetaste auf einer Zeile, um sie zu öffnen.',
  'Something went wrong': 'Etwas ist schiefgelaufen',
  Code: 'Code',
  'Request ID': 'Anfrage-ID',
  'Clear search': 'Suche löschen',
  'Drop the file to select it': 'Datei loslassen, um sie auszuwählen',
  'Drag a file here, or': 'Datei hierher ziehen oder',
  'Choose file…': 'Datei auswählen …',
  'Choose a file to upload': 'Datei zum Hochladen auswählen',
  '{items} pages': 'Seiten: {items}',
  '{start}–{end} of {total} {items}': '{start}–{end} von {total} {items}',
  '{total} {items}': '{total} {items}',
  'Close inspector': 'Inspektor schließen',

  // Errors (utils/errors.ts, services/apiClient.ts)
  'The file is larger than the upload limit. Split it, or raise the limit in the server settings.':
    'Die Datei ist größer als die Upload-Grenze. Teilen Sie sie auf oder erhöhen Sie die Grenze in den Servereinstellungen.',
  'Upload an XLSX, CSV, TSV, TXT or GAEB (.x81, .x83, .x84) file whose content matches its extension.':
    'Laden Sie eine XLSX-, CSV-, TSV-, TXT- oder GAEB-Datei (.x81, .x83, .x84) hoch, deren Inhalt zur Dateiendung passt.',
  'The file failed a safety check. Export it again from the program that created it (a spreadsheet: save it again as XLSX or CSV) and upload that copy.':
    'Die Datei hat eine Sicherheitsprüfung nicht bestanden. Exportieren Sie sie erneut aus dem Programm, mit dem sie erstellt wurde (eine Tabelle: erneut als XLSX oder CSV speichern), und laden Sie diese Kopie hoch.',
  'Sign in again with a valid access token.': 'Melden Sie sich erneut mit einem gültigen Zugangstoken an.',
  'It was changed in the meantime (for example in another tab). Reload it, check it and try again.':
    'Es wurde inzwischen geändert (zum Beispiel in einem anderen Tab). Laden Sie es neu, prüfen Sie es und versuchen Sie es erneut.',
  "This decision is not allowed from the issue's current status, which may have changed in the meantime. Reload the issue and check its status.":
    'Diese Entscheidung ist im aktuellen Status des Befunds nicht zulässig; der Status hat sich womöglich inzwischen geändert. Laden Sie den Befund neu und prüfen Sie seinen Status.',
  'Invalid value.': 'Ungültiger Wert.',
  'Step {number}: {problem}': 'Schritt {number}: {problem}',
  'An unexpected error occurred.': 'Ein unerwarteter Fehler ist aufgetreten.',
  'The server could not be reached. Check that the backend is running, then try again.':
    'Der Server ist nicht erreichbar. Prüfen Sie, ob das Backend läuft, und versuchen Sie es dann erneut.',
  'The server returned a response that is not valid JSON.': 'Der Server hat eine Antwort gesendet, die kein gültiges JSON ist.',
  'The server responded with HTTP {status}.': 'Der Server hat mit HTTP {status} geantwortet.',

  // Source locations (utils/sourceLocation.ts)
  'record {number}': 'Datensatz {number}',
  'field {number}': 'Feld {number}',
  'row {number}': 'Zeile {number}',
  'column {number}': 'Spalte {number}',
  'XML line {number}': 'XML-Zeile {number}',
  'line {number}': 'Dateizeile {number}',
  'paragraph {number}': 'Absatz {number}',
  'page {number}': 'Seite {number}',
  "Sheet '{sheet}' cell {cell}": "Blatt '{sheet}', Zelle {cell}",
  "Sheet '{sheet}'": "Blatt '{sheet}'",
  'Sheet cell {cell}': 'Blatt, Zelle {cell}',
  Sheet: 'Blatt',
  '{kind} page {number}': '{kind} Seite {number}',
  '{kind} page unknown': '{kind} Seite unbekannt',

  // Evidence classes
  'Rule violation': 'Regelverstoß',
  'Suspected anomaly': 'Vermutete Auffälligkeit',
  'Semantic warning': 'Semantischer Hinweis',
  'Extraction uncertainty': 'Unsichere Auslesung',
  'Needs external context': 'Externer Kontext nötig',
  'Human-confirmed': 'Manuell bestätigt',
  'A deterministic rule failed on verified input data.': 'Eine deterministische Regel ist bei geprüften Eingabedaten verletzt.',
  'A statistical signal: an unusual observation, not a proven error.':
    'Ein statistisches Signal: eine ungewöhnliche Beobachtung, kein nachgewiesener Fehler.',
  'A possible inconsistency found through text or semantic analysis.':
    'Ein möglicher Widerspruch, gefunden durch Text- oder semantische Analyse.',
  'The original document could not be interpreted reliably.': 'Das Originaldokument konnte nicht zuverlässig ausgelesen werden.',
  'Cannot be resolved from this document alone.': 'Lässt sich mit diesem Dokument allein nicht klären.',
  'A reviewer explicitly confirmed this finding.': 'Ein Prüfer hat diesen Befund ausdrücklich bestätigt.',

  // Finding categories
  Error: 'Fehler',
  Omission: 'Lücke',
  Inconsistency: 'Widerspruch',
  Ambiguity: 'Unklarheit',
  'Change order opportunity': 'Nachtragspotenzial',
  'Reading the file': 'Auslesen der Datei',
  'Would be objectively wrong.': 'Wäre objektiv falsch.',
  'Work the bill needs, or says is paid separately, for which no position pays.':
    'Leistung, die das Leistungsverzeichnis braucht oder als gesondert vergütet bezeichnet, für die aber keine Position vergütet.',
  'Two or more positions contradict each other.': 'Zwei oder mehr Positionen widersprechen sich.',
  'A description leaves open what to do or supply.': 'Eine Beschreibung lässt offen, was auszuführen oder zu liefern ist.',
  'Clear, but may cost the bidder money or time, or lead to a dispute.':
    'Eindeutig, kann den Bieter aber Geld oder Zeit kosten oder zu einem Streit führen.',
  'The bill admits that conditions or decisions stay open until after award.':
    'Das Leistungsverzeichnis räumt ein, dass Bedingungen oder Entscheidungen bis nach der Vergabe offen bleiben.',
  'About reading the file (a value that could not be read reliably, an unknown unit, a missing formula result, a total whose rows or rounding cannot be told apart), not about the bill itself.':
    'Betrifft das Auslesen der Datei (ein Wert, der nicht zuverlässig gelesen werden konnte, eine unbekannte Einheit, ein fehlendes Formelergebnis, eine Summe, deren Zeilen oder Rundung sich nicht auseinanderhalten lassen), nicht das Leistungsverzeichnis selbst.',

  // Anomaly types
  Price: 'Preis',
  Text: 'Text',

  // Severities
  Critical: 'Kritisch',
  High: 'Hoch',
  Medium: 'Mittel',
  Low: 'Niedrig',
  Info: 'Info',

  // Statuses
  Stored: 'Gespeichert',
  Processed: 'Verarbeitet',
  'Needs review': 'Prüfung nötig',
  Failed: 'Fehlgeschlagen',
  OK: 'OK',
  Queued: 'In Warteschlange',
  Running: 'Läuft',
  Completed: 'Abgeschlossen',
  'Completed with errors': 'Mit Fehlern abgeschlossen',
  'In progress': 'In Bearbeitung',
  Finished: 'Beendet',
  Skipped: 'Übersprungen',
  Stopped: 'Angehalten',
  'Pending review': 'Ungeprüft',
  'Confirmed error': 'Bestätigter Fehler',
  'False positive': 'Fehlalarm',
  'Needs more information': 'Weitere Informationen nötig',
  Dismissed: 'Verworfen',
  Corrected: 'Korrigiert',

  // Row kinds
  Item: 'Position',
  Section: 'Abschnitt',
  Subtotal: 'Zwischensumme',
  'Grand total': 'Gesamtsumme',
  Tax: 'Steuer',
  'Gross total': 'Bruttosumme',
  Adjustment: 'Anpassung',
  'Carried forward': 'Übertrag',
  'Summary line': 'Summenzeile',
  Blank: 'Leerzeile',

  // Parse statuses
  Exact: 'Exakt',
  Inferred: 'Abgeleitet',
  Ambiguous: 'Mehrdeutig',
  Unavailable: 'Nicht verfügbar',
  'Not applicable': 'Entfällt',
  Marker: 'Kennzeichen',
  'Needed column- or document-level evidence to interpret.': 'Zur Deutung waren Hinweise aus der Spalte oder dem Dokument nötig.',
  'More than one interpretation remained; no value was chosen.': 'Mehrere Deutungen blieben möglich; es wurde kein Wert gewählt.',
  'The text did not match the expected type.': 'Der Text passte nicht zum erwarteten Typ.',
  'The source holds no value (for example a formula without a cached result).':
    'Die Quelle enthält keinen Wert (zum Beispiel eine Formel ohne gespeichertes Ergebnis).',
  'A word or sign stands where a number would be; no number was invented.':
    'Ein Wort oder Zeichen steht an der Stelle einer Zahl; es wurde keine Zahl erfunden.',

  // Value markers
  'Nil: nothing to price, counts as zero.': 'Null: nichts zu bepreisen, zählt als null.',
  'Included elsewhere: priced in another item.': 'Anderweitig enthalten: in einer anderen Position bepreist.',
  'Not applicable: the item does not apply.': 'Entfällt: die Position kommt nicht zur Anwendung.',
  'By others: supplied by another party.': 'Durch Dritte: von einer anderen Partei geliefert.',
  'Rate only: priced as a unit rate only.': 'Nur Einheitspreis: nur als Einheitspreis bepreist.',
  'Lump sum: the quantity is written as a lump-sum token.': 'Pauschal: die Menge ist als Pauschalangabe geschrieben.',
  'Not offered: the bidder gives no price; counts as zero.': 'Nicht angeboten: der Bieter nennt keinen Preis; zählt als null.',

  // Why a detector stopped early

  // Data types
  Empty: 'Leer',
  Number: 'Zahl',
  Date: 'Datum',
  Boolean: 'Wahrheitswert',
  Mixed: 'Gemischt',

  // Column mapping and header detection

  // Detector categories
  'Machine learning': 'Maschinelles Lernen',

  // Evidence kinds
  Calculation: 'Berechnung',
  Value: 'Wert',
  Rule: 'Regel',
  Comparison: 'Vergleich',
  Reference: 'Verweis',
  Note: 'Notiz',

  // Audit actions
  'Document uploaded': 'Dokument hochgeladen',
  'Dataset created': 'Datensatz erstellt',
  'Validation run completed': 'Prüflauf abgeschlossen',
  'Review finished': 'Prüfung beendet',
  'Review reopened': 'Prüfung wieder geöffnet',
  'Issue reviewed': 'Befund geprüft',
  'Correction proposed': 'Korrektur vorgeschlagen',
  'Correction applied': 'Korrektur übernommen',
  Cancel: 'Abbrechen',
};
