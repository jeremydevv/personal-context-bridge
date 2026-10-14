// Read-only Apple Notes inventory. Run with: osascript -l JavaScript notes_snapshot.js
(() => {
    const app = Application("Notes");
    const references = app.notes();
    const notes = [];
    let missingBodies = 0;
    for (const note of references) {
        const folder = note.container().name();
        if (folder === "Recently Deleted") continue;
        let body = "";
        let contentAvailable = true;
        try {
            body = note.plaintext();
            if (typeof body !== "string") {
                body = "";
                contentAvailable = false;
            }
        } catch (_) {
            contentAvailable = false;
        }
        if (!contentAvailable) missingBodies++;
        notes.push({
            id: note.id(),
            title: note.name(),
            body: body,
            folder: folder,
            createdAt: note.creationDate().toISOString(),
            modifiedAt: note.modificationDate().toISOString(),
            contentAvailable: contentAvailable
        });
    }
    return JSON.stringify({success: true, count: notes.length, missingBodies: missingBodies, notes: notes});
})()
