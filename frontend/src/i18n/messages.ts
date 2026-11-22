/**
 * The interface texts in English and German, by key. English is the default and the fallback:
 * a key missing from German shows its English text, and a key missing from both shows itself.
 * `{name}` placeholders are filled from the second argument of `t()`.
 *
 * Two kinds of key: dotted keys (`nav.projects`) with both texts here, for the frame, Settings
 * and sign-in; and the English text itself (`t('Page not found')`), with its German in
 * `./de/`, for the pages' content. Text that is no key at all, such as a value from the backend
 * or an uploaded bill, comes back unchanged.
 *
 * Outside React (label tables, formatters, helpers called while rendering) use the module-level
 * `t`, which reads the language the I18nProvider applied. Constant tables built at module load
 * mark their English with `msg` and are translated with `t` where they are shown.
 */
import { cloneElement, isValidElement } from 'react';
import { DE } from './de/index.ts';
import type { ReactNode } from 'react';

export const LANGUAGES = Object.freeze<{ id: Language; label: string; short: string }[]>([
  { id: 'en', label: 'English', short: 'EN' },
  { id: 'de', label: 'Deutsch', short: 'DE' },
]);

export type Language = 'en' | 'de';

export const DEFAULT_LANGUAGE: Language = 'en';

/** The BCP 47 locale of each language, for Intl formatting and React Aria. */
const INTL_LOCALES = Object.freeze({ en: 'en-US', de: 'de-DE' });

const en = {
  'app.name': 'Desvio',
  'shell.skip': 'Skip to main content',
  'shell.topBar': 'Top bar',
  'phone.title': 'Desvio works best on a computer',
  'phone.description': 'Review project files, check quantities and explore findings on a larger screen. Send this link to yourself and open it on your computer.',
  'phone.shareText': 'Open Desvio on your computer:',
  'phone.whatsapp': 'Send with WhatsApp',
  'phone.email': 'Send by email',
  'phone.share': 'Share link',
  'phone.copy': 'Copy link',
  'phone.copied': 'Link copied',
  'phone.continue': 'Continue on this phone',
  'phone.emailSubject': 'Open Desvio on your computer',

  'nav.label': 'Primary',
  'nav.open': 'Open the navigation',
  'nav.close': 'Close the navigation',
  'nav.projects': 'Projects',
  'nav.users': 'Users',
  'project.nav.label': 'Project',
  'project.nav.overview': 'Overview',
  'project.nav.workspace': 'Workspace',
  'project.nav.followUps': 'Follow-ups',
  'project.nav.reports': 'Reports',
  'nav.settings': 'Settings',
  'nav.notFound': 'Page not found',
  'projects.column.description': 'Description',
  'projects.file.reference': 'Reference',
  'projects.file.references': 'References',

  'role.admin': 'Administrator',
  'role.reviewer': 'Reviewer',
  'role.viewer': 'Viewer',
  'role.admin.description': 'Everything a reviewer can do, and manages the user accounts.',
  'role.reviewer.description': 'Uploads bills, runs the checks, reviews findings and makes corrections.',
  'role.viewer.description': 'Reads bills, findings and reports; changes nothing.',

  'permission.read': 'Read bills, findings and reports',
  'permission.write': 'Upload, check, review and correct',
  'permission.manage_users': 'Manage user accounts',

  'profile.open': 'Open the user menu of {name}',
  'profile.currentReviewer': 'Current reviewer: {name}',
  'profile.menu': 'User menu',
  'menu.profile': 'Profile',
  'menu.logout': 'Log out',
  'profile.noEmail': 'No email address',
  'profile.details.title': 'Personal details',
  'profile.details.description': 'Your name and how to reach you. Colleagues see your name in the history of decisions.',
  'profile.firstName': 'First name',
  'profile.lastName': 'Last name',
  'profile.email': 'Email',
  'profile.jobTitle': 'Job title',
  'profile.phone': 'Phone',
  'profile.firstNameMissing': 'Enter your first name.',
  'profile.emailInvalid': 'Enter an email address such as name@example.com, or leave it empty.',
  'profile.phoneInvalid': 'Use digits, spaces and + ( ) - / . only.',
  'profile.save': 'Save changes',
  'profile.reset': 'Undo changes',
  'profile.saved': 'Your profile is saved.',
  'profile.saveFailed': 'Your profile was not saved: {message}',
  'profile.access.title': 'Role and access',
  'profile.access.description': 'Only an administrator can change your role or deactivate your account.',
  'profile.roleMeans': 'What it means',
  'profile.status': 'Status',
  'profile.memberSince': 'Member since',
  'profile.token': 'Access token',
  'profile.tokenIssued': 'issued',
  'profile.noAccount.title': 'Sign in to your own profile',
  'profile.noAccount.body': 'Enter the personal access token an administrator gave you.',
  'profile.role': 'Role',
  'profile.can': 'What you can do',
  'profile.allowed': 'Allowed',
  'profile.notAllowed': 'Not allowed',
  'profile.tokenLabel': 'Personal access token',
  'profile.tokenHelp': 'An administrator creates it on the Users page. It is kept for this browser tab only.',
  'profile.tokenSubmit': 'Sign in',
  'profile.tokenCancel': 'Cancel',
  'profile.tokenMissing': 'Enter the access token.',
  'profile.tokenNotUser': 'This token does not belong to an active user account.',
  'profile.tokenRejected': 'This access token was not accepted. Check it and try again.',
  'profile.tokenFailed': 'The token could not be checked: {message}',
  'profile.loading': 'Loading your profile…',
  'profile.readOnly': 'Read only',
  'profile.readOnlyHint': 'Your role can read but not change anything.',
  'profile.localUser': 'Local administrator',
  'profile.serviceUser': 'Administrator (configured token)',

  'language.label': 'Language',
  'language.switchTo': 'Switch the language to {language}',

  'settings.title': 'Settings',
  'settings.sections': 'Settings sections',
  'settings.tab.general': 'General',
  'settings.tab.accessibility': 'Accessibility',
  'a11y.title': 'Accessibility',
  'a11y.description': 'Make the interface easier to see, read and use. Changes apply at once and are kept in this browser.',
  'a11y.reset': 'Reset to defaults',
  'a11y.textSize': 'Text size',
  'a11y.textSize.description': 'Everything grows with the text, the layout included.',
  'a11y.textSize.default': 'Default',
  'a11y.textSize.large': 'Large',
  'a11y.textSize.larger': 'Larger',
  'a11y.contrast': 'Contrast',
  'a11y.contrast.description': 'High contrast makes secondary text, borders and the focus ring stronger, in light and dark.',
  'a11y.contrast.system': 'Follow system',
  'a11y.contrast.standard': 'Standard',
  'a11y.contrast.high': 'High',
  'a11y.motion': 'Motion',
  'a11y.motion.description': 'Reduce motion stops animations, smooth scrolling and the build-up of the 3D model.',
  'a11y.motion.system': 'Follow system',
  'a11y.motion.reduce': 'Reduce motion',
  'a11y.reading': 'Reading and navigation',
  'a11y.reading.description': 'Help for reading text and for finding your place with the keyboard.',
  'a11y.underlineLinks': 'Underline links',
  'a11y.underlineLinks.description': 'Links are underlined, so they do not depend on colour alone.',
  'a11y.readableText': 'Easier reading spacing',
  'a11y.readableText.description': 'More space between letters, words and lines, which helps many readers, including people with dyslexia.',
  'a11y.strongFocus': 'Strong focus ring',
  'a11y.strongFocus.description': 'A thicker outline with a halo shows where the keyboard is.',
  'a11y.keyboard': 'Keyboard',
  'a11y.keyboard.skip.key': 'Tab',
  'a11y.keyboard.skip': 'First Tab on a page: Skip to main content.',
  'a11y.keyboard.tab.key': 'Tab',
  'a11y.keyboard.tab': 'Moves between controls; Shift+Tab moves back.',
  'a11y.keyboard.escape.key': 'Esc',
  'a11y.keyboard.escape': 'Closes menus, panels and dialogs.',
  'a11y.keyboard.arrows.key': 'Arrows',
  'a11y.keyboard.arrows': 'Move between tabs, menu items and table rows; Enter opens.',
  'settings.tab.system': 'System',

  'general.language.title': 'Language',
  'general.language.description':
    'The language of the interface and of its number and date formats, for this browser. Uploaded bills and documents, and the findings and reports made from them, keep the language of their source.',
  'general.language.current': 'The interface is in English.',
  'appearance.title': 'Appearance',
  'appearance.description': 'Light, dark, or the setting of your system, for this browser.',
  'appearance.label': 'Colour scheme',
  'appearance.system': 'System',
  'appearance.light': 'Light',
  'appearance.dark': 'Dark',

  'users.title': 'User accounts',
  'users.add': 'Add user',
  'users.back': 'Back to all users',
  'users.addTitle': 'New user',
  'users.email': 'Email (optional)',
  'users.role': 'Role',
  'users.create': 'Create user',
  'users.cancel': 'Cancel',
  'users.nameMissing': 'Enter a name.',
  'users.emailInvalid': 'Enter an email address such as name@example.com, or leave it empty.',
  'users.empty': 'No user accounts yet',
  'users.search': 'Search users',
  'users.allRoles': 'All roles',
  'users.allStatuses': 'All statuses',
  'users.noMatch': 'No accounts match the search and filters',
  'users.emptyHint': 'Add the people who review bills. Each gets a personal access token.',
  'users.loading': 'Loading the user accounts…',
  'users.loadFailed': 'The user accounts could not be loaded',
  'users.column.user': 'User',
  'users.item': 'account',
  'users.items': 'accounts',
  'users.column.role': 'Role',
  'users.column.status': 'Status',
  'users.column.token': 'Access token',
  'users.column.actions': 'Actions',
  'users.active': 'Active',
  'users.inactive': 'Deactivated',
  'users.statusOf': 'Status of {name}',
  'users.you': 'You',
  'users.tokenEnding': 'ends in {hint}',
  'users.noToken': 'None',
  'users.roleOf': 'Role of {name}',
  'users.newToken': 'New token',
  'users.newTokenFor': 'Issue a new access token for {name}',
  'users.deactivate': 'Deactivate',
  'users.activate': 'Activate',
  'users.deactivateFor': 'Deactivate {name}',
  'users.activateFor': 'Activate {name}',
  'users.edit': 'Edit',
  'users.saveFailed': 'The details were not saved: {message}',
  'users.delete': 'Delete',
  'users.deleteFor': 'Delete {name}',
  'users.confirmDelete': 'Delete {name}? Their access token stops working. The history keeps their name.',
  'users.confirmDeleteYes': 'Delete user',
  'users.tokenTitle': 'Access token for {name}',
  'users.tokenBody':
    'Copy it now and give it to {name}: it is shown only once. They sign in with it under Profile in the user menu (their name at the top right), or in the sign-in dialog when the server requires sign-in.',
  'users.copyToken': 'Copy token',
  'users.dismissToken': 'Done',
  'users.adminOnly': 'Only administrators manage user accounts',
  'users.adminOnlyHint': 'You are signed in as {name} ({role}). Ask an administrator to add people or change roles.',
  'users.actionFailed': 'The change was not saved',

  'signIn.title': 'Sign in to Desvio',
  'signIn.description':
    'This server requires an access token. Ask the person who runs it for one. The token is kept for this browser tab only.',
  'signIn.label': 'Access token',
  'signIn.help': 'Sent with every request as a bearer token. Log out from the menu of your avatar (top right).',
  'signIn.missing': 'Enter your access token.',
  'signIn.notAccepted': 'This access token was not accepted. Check it and try again.',
  'signIn.failed': 'The token could not be checked: {message}',
  'signIn.checking': 'Checking…',
  'signIn.submit': 'Sign in',
  'signIn.rejected': 'The server did not accept your access token, or it is no longer valid. Enter it again.',
  'signIn.signedOut': 'You signed out. Enter an access token to continue.',

  'page.projects': 'Projects',
  'page.projects.all': 'All projects',
  'page.projects.description': 'Explore a ready-made project, or create your own and add its files.',
  'page.history': 'History',
  'page.notFound': 'Page not found',
  'page.notFound.empty': 'There is nothing at this address',
  'page.notFound.noMatch': 'No page matches',
  'page.notFound.action': 'Go to projects',
};

const de = {
  ...DE,
  'app.name': 'Desvio',
  'shell.skip': 'Zum Hauptinhalt springen',
  'shell.topBar': 'Kopfleiste',
  'phone.title': 'Desvio funktioniert am besten am Computer',
  'phone.description': 'Prüfen Sie Projektdateien, Mengen und Befunde auf einem größeren Bildschirm. Senden Sie sich den Link und öffnen Sie ihn am Computer.',
  'phone.shareText': 'Desvio am Computer öffnen:',
  'phone.whatsapp': 'Mit WhatsApp senden',
  'phone.email': 'Per E-Mail senden',
  'phone.share': 'Link teilen',
  'phone.copy': 'Link kopieren',
  'phone.copied': 'Link kopiert',
  'phone.continue': 'Auf diesem Telefon fortfahren',
  'phone.emailSubject': 'Desvio am Computer öffnen',

  'nav.label': 'Hauptnavigation',
  'nav.open': 'Navigation öffnen',
  'nav.close': 'Navigation schließen',
  'nav.projects': 'Projekte',
  'nav.users': 'Benutzer',
  'project.nav.label': 'Projekt',
  'project.nav.overview': 'Übersicht',
  'project.nav.workspace': 'Arbeitsbereich',
  'project.nav.followUps': 'Nachverfolgung',
  'project.nav.reports': 'Berichte',
  'nav.settings': 'Einstellungen',
  'nav.notFound': 'Seite nicht gefunden',
  'projects.column.description': 'Beschreibung',
  'projects.file.reference': 'Vergleichsunterlage',
  'projects.file.references': 'Vergleichsunterlagen',

  'role.admin': 'Administrator',
  'role.reviewer': 'Prüfer',
  'role.viewer': 'Leser',
  'role.admin.description': 'Alles, was ein Prüfer darf, und verwaltet die Benutzerkonten.',
  'role.reviewer.description': 'Lädt LVs hoch, startet Prüfungen, bewertet Befunde und korrigiert.',
  'role.viewer.description': 'Liest LVs, Befunde und Berichte; ändert nichts.',

  'permission.read': 'LVs, Befunde und Berichte lesen',
  'permission.write': 'Hochladen, prüfen, bewerten und korrigieren',
  'permission.manage_users': 'Benutzerkonten verwalten',

  'profile.open': 'Benutzermenü von {name} öffnen',
  'profile.currentReviewer': 'Aktueller Prüfer: {name}',
  'profile.menu': 'Benutzermenü',
  'menu.profile': 'Profil',
  'menu.logout': 'Abmelden',
  'profile.noEmail': 'Keine E-Mail-Adresse',
  'profile.details.title': 'Persönliche Angaben',
  'profile.details.description': 'Ihr Name und wie man Sie erreicht. Kollegen sehen Ihren Namen im Verlauf der Entscheidungen.',
  'profile.firstName': 'Vorname',
  'profile.lastName': 'Nachname',
  'profile.email': 'E-Mail',
  'profile.jobTitle': 'Position',
  'profile.phone': 'Telefon',
  'profile.firstNameMissing': 'Geben Sie Ihren Vornamen ein.',
  'profile.emailInvalid': 'Geben Sie eine E-Mail-Adresse wie name@beispiel.de ein oder lassen Sie das Feld leer.',
  'profile.phoneInvalid': 'Nur Ziffern, Leerzeichen und + ( ) - / . verwenden.',
  'profile.save': 'Änderungen speichern',
  'profile.reset': 'Änderungen verwerfen',
  'profile.saved': 'Ihr Profil ist gespeichert.',
  'profile.saveFailed': 'Ihr Profil wurde nicht gespeichert: {message}',
  'profile.access.title': 'Rolle und Zugriff',
  'profile.access.description': 'Nur ein Administrator kann Ihre Rolle ändern oder Ihr Konto deaktivieren.',
  'profile.roleMeans': 'Bedeutung',
  'profile.status': 'Status',
  'profile.memberSince': 'Mitglied seit',
  'profile.token': 'Zugangstoken',
  'profile.tokenIssued': 'ausgestellt',
  'profile.noAccount.title': 'Bei Ihrem eigenen Profil anmelden',
  'profile.noAccount.body': 'Geben Sie das persönliche Zugangstoken ein, das Sie von einem Administrator erhalten haben.',
  'profile.role': 'Rolle',
  'profile.can': 'Was Sie dürfen',
  'profile.allowed': 'Erlaubt',
  'profile.notAllowed': 'Nicht erlaubt',
  'profile.tokenLabel': 'Persönliches Zugangstoken',
  'profile.tokenHelp': 'Ein Administrator erstellt es auf der Seite Benutzer. Es gilt nur für diesen Browser-Tab.',
  'profile.tokenSubmit': 'Anmelden',
  'profile.tokenCancel': 'Abbrechen',
  'profile.tokenMissing': 'Geben Sie das Zugangstoken ein.',
  'profile.tokenNotUser': 'Dieses Token gehört zu keinem aktiven Benutzerkonto.',
  'profile.tokenRejected': 'Dieses Zugangstoken wurde nicht angenommen. Prüfen Sie es und versuchen Sie es erneut.',
  'profile.tokenFailed': 'Das Token konnte nicht geprüft werden: {message}',
  'profile.loading': 'Ihr Profil wird geladen…',
  'profile.readOnly': 'Nur lesen',
  'profile.readOnlyHint': 'Ihre Rolle darf lesen, aber nichts ändern.',
  'profile.localUser': 'Lokaler Administrator',
  'profile.serviceUser': 'Administrator (konfiguriertes Token)',

  'language.label': 'Sprache',
  'language.switchTo': 'Sprache auf {language} umstellen',

  'settings.title': 'Einstellungen',
  'settings.sections': 'Bereiche der Einstellungen',
  'settings.tab.general': 'Allgemein',
  'settings.tab.accessibility': 'Barrierefreiheit',
  'a11y.title': 'Barrierefreiheit',
  'a11y.description': 'Die Oberfläche leichter sehen, lesen und bedienen. Änderungen gelten sofort und bleiben in diesem Browser gespeichert.',
  'a11y.reset': 'Auf Standard zurücksetzen',
  'a11y.textSize': 'Textgröße',
  'a11y.textSize.description': 'Alles wächst mit dem Text, auch das Layout.',
  'a11y.textSize.default': 'Standard',
  'a11y.textSize.large': 'Groß',
  'a11y.textSize.larger': 'Größer',
  'a11y.contrast': 'Kontrast',
  'a11y.contrast.description': 'Hoher Kontrast verstärkt Nebentexte, Rahmen und den Fokusrahmen, hell wie dunkel.',
  'a11y.contrast.system': 'Wie das System',
  'a11y.contrast.standard': 'Standard',
  'a11y.contrast.high': 'Hoch',
  'a11y.motion': 'Bewegung',
  'a11y.motion.description': 'Weniger Bewegung stoppt Animationen, weiches Scrollen und den Aufbau des 3D-Modells.',
  'a11y.motion.system': 'Wie das System',
  'a11y.motion.reduce': 'Bewegung reduzieren',
  'a11y.reading': 'Lesen und Navigieren',
  'a11y.reading.description': 'Hilfen beim Lesen und beim Wiederfinden der Position mit der Tastatur.',
  'a11y.underlineLinks': 'Links unterstreichen',
  'a11y.underlineLinks.description': 'Links sind unterstrichen und hängen nicht allein von der Farbe ab.',
  'a11y.readableText': 'Leichter lesbare Abstände',
  'a11y.readableText.description': 'Mehr Abstand zwischen Buchstaben, Wörtern und Zeilen; das hilft vielen, auch Menschen mit Legasthenie.',
  'a11y.strongFocus': 'Kräftiger Fokusrahmen',
  'a11y.strongFocus.description': 'Ein dickerer Rahmen mit Schein zeigt, wo die Tastatur gerade ist.',
  'a11y.keyboard': 'Tastatur',
  'a11y.keyboard.skip.key': 'Tab',
  'a11y.keyboard.skip': 'Erstes Tab auf einer Seite: Zum Hauptinhalt springen.',
  'a11y.keyboard.tab.key': 'Tab',
  'a11y.keyboard.tab': 'Wechselt zwischen Bedienelementen; Umschalt+Tab zurück.',
  'a11y.keyboard.escape.key': 'Esc',
  'a11y.keyboard.escape': 'Schließt Menüs, Bereiche und Dialoge.',
  'a11y.keyboard.arrows.key': 'Pfeile',
  'a11y.keyboard.arrows': 'Wechseln zwischen Reitern, Menüpunkten und Tabellenzeilen; Enter öffnet.',
  'settings.tab.system': 'System',

  'general.language.title': 'Sprache',
  'general.language.description':
    'Die Sprache der Oberfläche und ihrer Zahlen- und Datumsformate, für diesen Browser. Hochgeladene LVs und Dokumente sowie die daraus erstellten Befunde und Berichte behalten die Sprache ihrer Quelle.',
  'general.language.current': 'Die Oberfläche ist auf Deutsch.',
  'appearance.title': 'Darstellung',
  'appearance.description': 'Hell, dunkel oder wie im System eingestellt, für diesen Browser.',
  'appearance.label': 'Farbschema',
  'appearance.system': 'System',
  'appearance.light': 'Hell',
  'appearance.dark': 'Dunkel',

  'users.title': 'Benutzerkonten',
  'users.add': 'Benutzer hinzufügen',
  'users.back': 'Zurück zu allen Benutzern',
  'users.addTitle': 'Neuer Benutzer',
  'users.email': 'E-Mail (optional)',
  'users.role': 'Rolle',
  'users.create': 'Benutzer anlegen',
  'users.cancel': 'Abbrechen',
  'users.nameMissing': 'Geben Sie einen Namen ein.',
  'users.emailInvalid': 'Geben Sie eine E-Mail-Adresse wie name@beispiel.de ein oder lassen Sie das Feld leer.',
  'users.empty': 'Noch keine Benutzerkonten',
  'users.search': 'Benutzer durchsuchen',
  'users.allRoles': 'Alle Rollen',
  'users.allStatuses': 'Alle Status',
  'users.noMatch': 'Keine Konten passen zur Suche und zu den Filtern',
  'users.emptyHint': 'Fügen Sie die Personen hinzu, die LVs prüfen. Jede erhält ein persönliches Zugangstoken.',
  'users.loading': 'Die Benutzerkonten werden geladen…',
  'users.loadFailed': 'Die Benutzerkonten konnten nicht geladen werden',
  'users.column.user': 'Benutzer',
  'users.item': 'Konto',
  'users.items': 'Konten',
  'users.column.role': 'Rolle',
  'users.column.status': 'Status',
  'users.column.token': 'Zugangstoken',
  'users.column.actions': 'Aktionen',
  'users.active': 'Aktiv',
  'users.inactive': 'Deaktiviert',
  'users.statusOf': 'Status von {name}',
  'users.you': 'Sie',
  'users.tokenEnding': 'endet auf {hint}',
  'users.noToken': 'Keins',
  'users.roleOf': 'Rolle von {name}',
  'users.newToken': 'Neues Token',
  'users.newTokenFor': 'Neues Zugangstoken für {name} ausstellen',
  'users.deactivate': 'Deaktivieren',
  'users.activate': 'Aktivieren',
  'users.deactivateFor': '{name} deaktivieren',
  'users.activateFor': '{name} aktivieren',
  'users.edit': 'Bearbeiten',
  'users.saveFailed': 'Die Angaben wurden nicht gespeichert: {message}',
  'users.delete': 'Löschen',
  'users.deleteFor': '{name} löschen',
  'users.confirmDelete': '{name} löschen? Das Zugangstoken funktioniert dann nicht mehr. Der Verlauf behält den Namen.',
  'users.confirmDeleteYes': 'Benutzer löschen',
  'users.tokenTitle': 'Zugangstoken für {name}',
  'users.tokenBody':
    'Kopieren Sie es jetzt und geben Sie es {name}: Es wird nur einmal angezeigt. Angemeldet wird damit im Benutzermenü (der eigene Name oben rechts) unter Profil oder im Anmeldedialog, wenn der Server eine Anmeldung verlangt.',
  'users.copyToken': 'Token kopieren',
  'users.dismissToken': 'Fertig',
  'users.adminOnly': 'Nur Administratoren verwalten Benutzerkonten',
  'users.adminOnlyHint':
    'Sie sind als {name} ({role}) angemeldet. Bitten Sie einen Administrator, Personen hinzuzufügen oder Rollen zu ändern.',
  'users.actionFailed': 'Die Änderung wurde nicht gespeichert',

  'signIn.title': 'Bei Desvio anmelden',
  'signIn.description':
    'Dieser Server verlangt ein Zugangstoken. Fragen Sie die Person, die ihn betreibt. Das Token gilt nur für diesen Browser-Tab.',
  'signIn.label': 'Zugangstoken',
  'signIn.help': 'Wird mit jeder Anfrage als Bearer-Token gesendet. Abmelden über das Menü Ihres Avatars (oben rechts).',
  'signIn.missing': 'Geben Sie Ihr Zugangstoken ein.',
  'signIn.notAccepted': 'Dieses Zugangstoken wurde nicht angenommen. Prüfen Sie es und versuchen Sie es erneut.',
  'signIn.failed': 'Das Token konnte nicht geprüft werden: {message}',
  'signIn.checking': 'Wird geprüft…',
  'signIn.submit': 'Anmelden',
  'signIn.rejected': 'Der Server hat Ihr Zugangstoken nicht angenommen, oder es ist nicht mehr gültig. Geben Sie es erneut ein.',
  'signIn.signedOut': 'Sie haben sich abgemeldet. Geben Sie ein Zugangstoken ein, um fortzufahren.',

  'page.projects': 'Projekte',
  'page.projects.all': 'Alle Projekte',
  'page.projects.description': 'Sehen Sie sich ein vorbereitetes Projekt an, oder legen Sie ein eigenes an und fügen Sie seine Dateien hinzu.',
  'page.history': 'Verlauf',
  'page.notFound': 'Seite nicht gefunden',
  'page.notFound.empty': 'Unter dieser Adresse gibt es nichts',
  'page.notFound.noMatch': 'Keine Seite passt zu',
  'page.notFound.action': 'Zu den Projekten',
};

export const MESSAGES: Readonly<Record<Language, Readonly<Record<string, string>>>> = Object.freeze({
  en: Object.freeze(en),
  de: Object.freeze(de),
});

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && value in MESSAGES;
}

export function translator(language: Language): (key: string, values?: Record<string, string | number>) => string {
  const table = MESSAGES[language] ?? MESSAGES[DEFAULT_LANGUAGE];
  return (key, values) => {
    const text = table[key] ?? MESSAGES[DEFAULT_LANGUAGE][key] ?? key;
    if (!values) return text;
    return text.replace(/\{(\w+)\}/g, (match, name) => (name in values ? String(values[name]) : match));
  };
}

let current: Language = DEFAULT_LANGUAGE;

/** Makes `language` the one the module-level `t` and the formatters use. Only the I18nProvider calls this. */
export function applyLanguage(language: string) {
  current = isLanguage(language) ? language : DEFAULT_LANGUAGE;
}

/** @returns the language applied by the I18nProvider */
export function getLocale(): Language {
  return current;
}

/** The BCP 47 locale for Intl formatting: "en-US" or "de-DE". */
export function intlLocale(language: Language = current) {
  return INTL_LOCALES[language] ?? INTL_LOCALES[DEFAULT_LANGUAGE];
}

/**
 * Marks English text for translation without translating it, for tables built at module load.
 */
export function msg<T extends string>(text: T): T {
  return text;
}

/**
 * The text of a key in the applied language, with `{name}` placeholders filled. Call it while
 * rendering or in an event handler, never at module load.
 */
export function t(key: string, values?: Record<string, string | number>): string {
  if (typeof key !== 'string') return key;
  return translator(current)(key, values);
}

/**
 * Like `t`, for a sentence with React elements in it: returns the parts as nodes to render.
 */
export function tRich(key: string, values: Record<string, ReactNode>): ReactNode[] {
  return translator(current)(key)
    .split(/(\{\w+\})/)
    .filter(Boolean)
    .map((part, index) => {
      const name = /^\{(\w+)\}$/.exec(part)?.[1];
      if (!name || !(name in values)) return part;
      const value = values[name];
      return isValidElement(value) ? cloneElement(value, { key: index }) : value;
    });
}
