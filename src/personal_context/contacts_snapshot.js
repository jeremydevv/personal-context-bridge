// Read-only Contacts.app snapshot. Run with: osascript -l JavaScript contacts_snapshot.js
(() => {
    const people = Application("Contacts").people();
    const fields = ["firstName", "middleName", "lastName", "nickname", "maidenName",
        "organization", "department", "jobTitle", "note", "homePage", "birthDate",
        "creationDate", "modificationDate", "title", "suffix"];
    const groups = ["emails", "phones", "addresses", "urls", "relatedNames",
        "instantMessages", "socialProfiles"];

    function plain(value) {
        if (value === null || value === undefined) return "";
        if (value instanceof Date) return value.toISOString();
        if (["string", "number", "boolean"].includes(typeof value)) return value;
        return String(value);
    }

    const contacts = people.map(person => {
        // Fetch one property set per person. Individual AppleEvents for every
        // field make a complete archive scan slow enough for Contacts to exit.
        const properties = person.properties();
        const contact = {id: plain(properties.id), name: plain(properties.name)};
        for (const key of fields) contact[key] = plain(properties[key]);
        for (const group of groups) {
            contact[group] = person[group]().map(item => {
                const entry = {};
                const details = item.properties();
                for (const key of Object.keys(details)) {
                    if (key !== "pcls") entry[key] = plain(details[key]);
                }
                return entry;
            });
        }
        return contact;
    });
    return JSON.stringify({success: true, count: contacts.length, contacts: contacts});
})()
