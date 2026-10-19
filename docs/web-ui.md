# The web UI

The UI is at the root of the installation's address. It has what a person who uses
the repositories needs (browsing them, search, upload and delete), a person's own
account, and everything an administrator keeps: users, roles, anonymous access,
repositories, blob stores and the installation's own settings.

- **Browsing.** A repository opens one folder at a time, with the way there as a path
  above it. Choosing a file shows everything known of it beside the folder: its size,
  type and four checksums (each with a button that copies it), who stored it and when,
  and a download link. Every folder and file has an address of its own, so a link to
  one can be shared. A group lists its members. A proxy shows what has been fetched
  through it so far. An APT, YUM, apk or NuGet repository also says how a machine is
  set up to use it: its key, its address and the account it signs in with, as commands
  to copy, with what is yours to fill in between angle brackets. A NuGet repository's
  are for `dotnet` and `nuget.config`, Chocolatey, PowerShell, and a debugger's symbols.
- **A component's page** says what a package version is, lists its files, and gives
  what to paste into a build or a shell to use it (for Maven, the dependency for
  Maven and for Gradle; for NuGet, `dotnet`, a `PackageReference`, Chocolatey and
  PowerShell), each with a copy button.
- **Search** is a box in the header of every screen: press `/` to reach it. The
  results page filters by format, repository, group, name and version, and by a
  file's checksum: paste an MD5, SHA-1, SHA-256 or SHA-512, and its length says which
  it is. A search is in the address, so it can be shared and gone back to. Search
  looks in hosted and proxy repositories: what a group serves is found in its members.
- **Upload** is offered for a hosted Raw, Maven, npm, PyPI, APT, YUM, apk or NuGet
  repository to whoever may add to it, from the repository ("Upload here") and
  from the navigation. The form has the fields the format needs: none for APT and
  NuGet, whose packages say where they go (a NuGet symbol package goes beside its
  package, whichever is chosen first), and a directory for YUM and apk. Files are
  chosen, or dropped onto a file field. It shows how much has been sent, and can be
  stopped. What the server refuses about a field is said at that field, which then
  has the keyboard; anything else is said above the button. A Docker image is
  pushed with a container client.
- **Delete** is offered to whoever may delete in the repository. A file or one
  version is deleted after a question. A folder is deleted, with everything under
  it, only after its name is typed. Each is removed as the format's own client would
  remove it, so the indexes stay right.
- **What you may not do is not offered.** Without the permission to add there is no
  upload, without the permission to delete no delete. The server decides in every
  case: the screens only leave out what it would refuse.
- **Your account** is under your name in the header: your API tokens, your password,
  and your preferences.
  - **API tokens.** A token gets a name, an expiry (never, 30 days, 90 days, a year,
    or a day you choose) and a limit: everything you may do, only read, or the
    permissions you choose. Its secret is shown once, when it is made, with a button
    that copies it. A token is revoked from the same page.
  - **Preferences** are kept in the browser: the mode, and whether `/` goes to the
    search box. They are reached from the mode menu too, by a visitor as well.
- **Administration** is shown to whoever holds the permission to read each part.
  - **Users.** Create a user with a password you type or have generated, and tick
    the roles they hold. A user's page changes their name, email, roles and state,
    sets a new password, lists and revokes their API tokens, and deletes them after
    you type their name. Your own account cannot be disabled or deleted there, and
    your own password is changed under your account, where you are asked for the one
    you have. A built-in user cannot be deleted. A user's page says where they sign
    in: here, or through a sign-in source, whose users have no password here.
  - **Roles.** A role's permissions are rows: choose what a row is about (a
    repository, or an area of administration), then the format, repository and
    action from lists. The pattern the row makes is shown with what it grants in
    words. A pattern the lists cannot make is typed by hand, and a role that was
    written through the API opens with nothing lost. The `admin` role is shown and
    cannot be changed.
  - **Anonymous access** is one switch, which asks before it is turned on, and shows
    what someone who is not signed in may then do. If the `anonymous` user is
    disabled, nothing is given though the switch is on, and the page says so.
  - **Authentication** lists where people sign in from, in the order they are
    asked: MegooArti's own users first, then each sign-in source, with how many
    users it has. A source is turned on or off, moved up or down, tested, and deleted
    after you type its name. Turning MegooArti's own users off asks first: only the
    built-in `admin` signs in here then. The default role, which every signed-in
    user has, is chosen from the roles. A source's name leads to its page, where its
    settings are changed and the redirect address to register at the provider is
    shown, with a copy button; New OIDC source makes one, off until it is turned on.
    A group's roles are rows: a group, and the role its members are given.
  - **Certificates** lists what the server trusts when it connects out over TLS,
    besides the usual public authorities, with each one's fingerprint and expiry.
    Fetch asks a server what it presents, its own certificate first; a certificate
    is trusted after a question that shows its whole fingerprint, to check with
    whoever runs the server. One can also be pasted in PEM, and removed.
  - **Manage repositories** lists every repository as it is set up. A new one is made
    on one page: choose the format and the type, and the page shows what that
    combination has. A hosted repository has a deployment policy; a proxy has its
    remote, how it signs in there, how long it trusts what it cached, and what it
    does when the remote fails; a group has its members, put in order with buttons;
    a hosted or proxy Maven repository has a version policy and a layout policy; a
    hosted APT repository has its suite, a hosted YUM repository the depth of its
    metadata, a proxy of APT, YUM or apk its remote's public keys, which a group
    checks it with, and a NuGet proxy its protocol (V3, or V2 for the Chocolatey
    community feed and the PowerShell Gallery) and a symbol server to pass on. A new
    proxy's remote starts as its format's public repository (Maven Central, the npm
    registry, PyPI, Docker Hub, Debian, Alpine; nuget.org for NuGet V3 and the
    Chocolatey community feed for V2; none for YUM and raw), and follows the format
    and the protocol chosen until another address is typed. A hosted NuGet repository takes a version once unless another policy is chosen. What
    cannot change later (name, format, type, blob store, version policy, suite, depth
    of the metadata, a NuGet proxy's protocol) is shown as it is and not as a field, beside the address the repository's clients use. A proxy's secret is
    typed and never shown: leave the field empty to keep the one that is stored. A
    repository's page also shows a proxy's state and last error, has it check
    everything with its remote again, rebuilds the index, and deletes the
    repository after you type its name. A hosted repository or a group of APT, YUM
    or apk shows its signing key, with the public key to copy or download, and
    signs with a new or an imported key after asking: every machine must then
    install the new public key. A group's page lists the members a check left out,
    with why.
  - **Blob stores** lists the stores with how many blobs each holds, their size and
    the space left, makes a new one, and deletes one that no repository uses. Its
    files stay on the disk. The store called `default` is always kept: a repository
    that names no blob store is put in it.
  - **System** shows the version, the schema's revision and whether it is the one this
    version expects, when the server started and what it runs on, the database's
    version, and the blob stores. The base URL is set there.
- **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
  browser keeps it over HTTPS, and over plain HTTP only on the machine itself
  (`localhost`). If you reach the UI over plain HTTP at another name or address,
  signing in will say that the browser did not keep the session: use HTTPS, or set
  `MEGOOARTI_SESSION_COOKIE_SECURE=false`. The sign-in screen also offers "Sign in
  with <name>" for each OIDC source that is on: the provider signs you in, and sends
  you back to where you were going. If it does not, the screen says why.
- **Anonymous access.** If it is on, a visitor who is not signed in sees what the
  anonymous user may browse, and a "Sign in" button. If it is off, the sign-in screen.
- **Light and dark.** The mode switch in the header chooses light, dark, or as the
  system says. The choice is kept in the browser.
- **Nothing is fetched from anywhere else.** Fonts, icons and scripts are served by
  MegooArti itself, so the UI works in a network with no way out. The UI sends a
  strict content security policy: only its own scripts run, and it cannot be framed.
- **Keyboard and screen readers.** Every screen can be used by keyboard alone, starts
  with a link that skips to its content, and meets WCAG 2.1 AA contrast in both modes.
  When a screen changes under the keyboard (a folder is entered, a file is deleted,
  another page of results is shown), the keyboard is put at what changed. `/` reaches
  the search box from anywhere that is not a place to type, and can be turned off
  under Preferences.
