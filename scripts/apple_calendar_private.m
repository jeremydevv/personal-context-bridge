// Guarded native EventKit extensions. Attendee factory/save pattern informed by
// BRO3886/go-eventkit a3dbabc9ea2b41f2725437ea1e58c6c53b835702 (MIT).
#import <EventKit/EventKit.h>
#import "apple_pim_attachment.h"

@interface NSObject (PCEventKit)
- (id)initWithFilepath:(NSURL *)path;
- (NSString *)UUID;
- (NSString *)fileName;
- (NSString *)fileFormat;
- (id)securityScopedLocalURLWrapper;
- (NSURL *)url;
- (NSArray *)attachments;
- (void)addAttachment:(id)attachment;
- (void)removeAttachment:(id)attachment;
- (BOOL)supportsAddingAttachments;
- (BOOL)allowsAttendeesModifications;
- (BOOL)currentUserMayActAsOrganizer;
+ (id)attendeeWithName:(NSString *)name emailAddress:(NSString *)email;
- (void)addAttendee:(id)attendee;
- (void)removeAttendee:(id)attendee;
- (void)addOrganizerAndSelfAttendeeForNewInvitation;
@end

static BOOL started = NO;
static NSString *stage = @"input";
static NSString *temporaryDirectory;
static void output(NSDictionary *result) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:nil];
    if (data) puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
}
static void cleanup(void) {
    if (temporaryDirectory) [[NSFileManager defaultManager] removeItemAtPath:temporaryDirectory error:nil];
}
static void fail(NSString *code) {
    cleanup(); output(@{@"success":@NO, @"write_started":@(started), @"error_code":code, @"stage":stage}); exit(0);
}
static NSDate *date(NSString *value) {
    NSISO8601DateFormatter *format = [NSISO8601DateFormatter new];
    NSDate *result = [format dateFromString:value];
    if (!result) { format.formatOptions |= NSISO8601DateFormatWithFractionalSeconds; result = [format dateFromString:value]; }
    if (!result) fail(@"invalid_fields");
    return result;
}
static EKEvent *find(EKEventStore *store, NSString *identifier, NSDate *start) {
    NSPredicate *predicate = [store predicateForEventsWithStartDate:[start dateByAddingTimeInterval:-1]
        endDate:[start dateByAddingTimeInterval:1] calendars:nil];
    NSMutableArray *matches = [NSMutableArray array];
    for (EKEvent *event in [store eventsMatchingPredicate:predicate]) {
        if ([event.eventIdentifier isEqual:identifier] && fabs([event.startDate timeIntervalSinceDate:start]) < 0.01) [matches addObject:event];
    }
    if (matches.count != 1) fail(@"item_not_found");
    return matches.firstObject;
}
static NSString *email(EKParticipant *participant) {
    NSString *value = participant.URL.resourceSpecifier ?: @"";
    return value.stringByRemovingPercentEncoding.lowercaseString ?: value.lowercaseString;
}
static NSArray *attachments(EKEvent *event) {
    if (![event respondsToSelector:@selector(attachments)]) return @[];
    NSMutableArray *result = [NSMutableArray array];
    for (id attachment in [event attachments]) {
        if (![attachment respondsToSelector:@selector(UUID)]) fail(@"unsupported_capability");
        id wrapper = [attachment respondsToSelector:@selector(securityScopedLocalURLWrapper)] ? [attachment securityScopedLocalURLWrapper] : nil;
        NSData *bytes = wrapper && [wrapper respondsToSelector:@selector(url)] ? PCLocalBytes([wrapper url]) : nil;
        [result addObject:@{@"attachment_id":[attachment UUID] ?: @"", @"filename":[attachment fileName] ?: @"",
            @"uti":[attachment fileFormat] ?: @"", @"available":@(bytes != nil),
            @"sha256":bytes ? PCSHA(bytes) : @"", @"bytes":@(bytes.length)}];
    }
    [result sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"attachment_id"] compare:b[@"attachment_id"]]; }];
    return result;
}
static NSDictionary *metadata(EKEvent *event) {
    return @{@"attachments":attachments(event),
        @"supports_attachments":@((BOOL)([event respondsToSelector:@selector(supportsAddingAttachments)] && [event supportsAddingAttachments])),
        @"supports_attendee_edits":@((BOOL)([event respondsToSelector:@selector(allowsAttendeesModifications)] && [event allowsAttendeesModifications])),
        @"may_act_as_organizer":@((BOOL)([event respondsToSelector:@selector(currentUserMayActAsOrganizer)] && [event currentUserMayActAsOrganizer]))};
}

int main(int argc, const char *argv[]) {
    @autoreleasepool { @try {
        if (argc != 2) fail(@"invalid_fields");
        NSData *input = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
        if (!input || input.length > 8388608) fail(@"invalid_fields");
        NSDictionary *fields = [NSJSONSerialization JSONObjectWithData:input options:0 error:nil];
        if (![fields isKindOfClass:NSDictionary.class]) fail(@"invalid_fields");
        if ([EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent] != EKAuthorizationStatusFullAccess) fail(@"receiver_unavailable");
        EKEventStore *store = [EKEventStore new];
        EKEvent *event = find(store, fields[@"item_id"], date(fields[@"occurrence_start_at"]));
        NSDictionary *before = metadata(event);
        if ([fields[@"operation"] isEqual:@"inspect"]) { output(@{@"success":@YES, @"metadata":before}); return 0; }
        if (![fields[@"operation"] isEqual:@"update_private"] || !event.calendar.allowsContentModifications) fail(@"read_only");
        NSDictionary *changes = fields[@"changes"];
        NSSet *allowed = [NSSet setWithArray:@[@"add_attendees", @"remove_attendees", @"allow_invitation_delivery", @"add_attachments", @"remove_attachments"]];
        if (![changes isKindOfClass:NSDictionary.class] || changes.count == 0 || ![[NSSet setWithArray:changes.allKeys] isSubsetOfSet:allowed]) fail(@"invalid_fields");
        BOOL attendeeChange = changes[@"add_attendees"] || changes[@"remove_attendees"];
        if ((attendeeChange || event.hasAttendees) && ![changes[@"allow_invitation_delivery"] isEqual:@YES]) fail(@"invalid_fields");
        if (attendeeChange) {
            if (![before[@"supports_attendee_edits"] boolValue] ||
                (event.hasAttendees && ![before[@"may_act_as_organizer"] boolValue])) fail(@"unsupported_capability");
            Class cls = NSClassFromString(@"EKAttendee");
            if (![cls respondsToSelector:@selector(attendeeWithName:emailAddress:)] ||
                ![event respondsToSelector:@selector(addAttendee:)] || ![event respondsToSelector:@selector(removeAttendee:)]) fail(@"unsupported_capability");
            if (!event.hasAttendees && changes[@"add_attendees"]) {
                if (![event respondsToSelector:@selector(addOrganizerAndSelfAttendeeForNewInvitation)]) fail(@"unsupported_capability");
                [event addOrganizerAndSelfAttendeeForNewInvitation];
            }
            for (NSString *target in changes[@"remove_attendees"]) {
                EKParticipant *match = nil;
                for (EKParticipant *person in event.attendees) if ([email(person) isEqual:target.lowercaseString]) match = person;
                if (!match || match.isCurrentUser || [email(match) isEqual:email(event.organizer)]) fail(@"invalid_fields");
                [event removeAttendee:match];
            }
            for (NSDictionary *spec in changes[@"add_attendees"]) {
                NSString *target = [spec[@"email"] lowercaseString];
                BOOL exists = NO;
                for (EKParticipant *person in event.attendees) if ([email(person) isEqual:target]) exists = YES;
                if (!exists) {
                    id person = [cls attendeeWithName:spec[@"name"] ?: spec[@"email"] emailAddress:spec[@"email"]];
                    if (!person) fail(@"invalid_fields");
                    [event addAttendee:person];
                }
            }
        }
        NSArray *oldAttachments = [event attachments];
        for (NSString *identifier in changes[@"remove_attachments"]) {
            id match = nil;
            for (id attachment in oldAttachments) if ([[attachment UUID] isEqual:identifier]) match = attachment;
            if (!match || ![event respondsToSelector:@selector(removeAttachment:)]) fail(@"invalid_fields");
            [event removeAttachment:match];
        }
        NSMutableArray *addedHashes = [NSMutableArray array];
        if (changes[@"add_attachments"]) {
            stage = @"attachment_capability";
            if (![before[@"supports_attachments"] boolValue]) fail(@"unsupported_capability");
            Class cls = NSClassFromString(@"EKAttachment");
            if (![cls instancesRespondToSelector:@selector(initWithFilepath:)] || ![event respondsToSelector:@selector(addAttachment:)]) fail(@"unsupported_capability");
            temporaryDirectory = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
            if (![[NSFileManager defaultManager] createDirectoryAtPath:temporaryDirectory withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil]) fail(@"native_error");
            for (NSDictionary *spec in changes[@"add_attachments"]) {
                NSUInteger width = 0, height = 0;
                NSData *data = PCFileData(spec, YES, &width, &height);
                if (!data) fail(@"invalid_fields");
                for (NSDictionary *old in before[@"attachments"]) if ([old[@"sha256"] isEqual:spec[@"sha256"]]) fail(@"invalid_fields");
                NSString *directory = [temporaryDirectory stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
                [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:NO attributes:@{NSFilePosixPermissions:@0700} error:nil];
                NSString *path = [directory stringByAppendingPathComponent:spec[@"filename"]];
                if (![data writeToFile:path options:0 error:nil]) fail(@"native_error");
                [[NSFileManager defaultManager] setAttributes:@{NSFilePosixPermissions:@0600} ofItemAtPath:path error:nil];
                stage = @"attachment_factory";
                id attachment = [[cls alloc] initWithFilepath:[NSURL fileURLWithPath:path]];
                if (!attachment) fail(@"unsupported_capability");
                [event addAttachment:attachment];
                [addedHashes addObject:spec[@"sha256"]];
            }
        }
        NSArray *expectedAttendees = [event.attendees valueForKey:@"URL"];
        NSMutableSet *expectedAttachmentIDs = [NSMutableSet set];
        for (id attachment in [event attachments]) if ([attachment UUID]) [expectedAttachmentIDs addObject:[attachment UUID]];
        NSDate *start = event.startDate;
        started = YES;
        stage = @"save";
        NSError *error = nil;
        if (![store saveEvent:event span:[fields[@"scope"] isEqual:@"future"] ? EKSpanFutureEvents : EKSpanThisEvent commit:YES error:&error]) fail(@"native_error");
        NSString *identifier = event.eventIdentifier;
        [store reset];
        EKEvent *saved = find(store, identifier, start);
        if (![[NSSet setWithArray:[saved.attendees valueForKey:@"URL"]] isEqual:[NSSet setWithArray:expectedAttendees]]) fail(@"verification_failed");
        NSArray *after = attachments(saved);
        stage = [NSString stringWithFormat:@"verify_attachment_ids:%lu:%lu", (unsigned long)expectedAttachmentIDs.count, (unsigned long)after.count];
        if (![[NSSet setWithArray:[after valueForKey:@"attachment_id"]] isEqual:expectedAttachmentIDs]) fail(@"verification_failed");
        stage = @"verify_attachment_bytes";
        for (NSString *hash in addedHashes) if (![[after valueForKey:@"sha256"] containsObject:hash]) fail(@"verification_failed");
        cleanup(); temporaryDirectory = nil;
        stage = @"verify_after_staging_cleanup";
        // Ensure the attachment is in EventKit's store, not our staging directory.
        for (NSString *hash in addedHashes) if (![[attachments(saved) valueForKey:@"sha256"] containsObject:hash]) fail(@"verification_failed");
        output(@{@"success":@YES, @"verified":@YES, @"item_id":identifier});
    } @catch (NSException *exception) { stage = [stage stringByAppendingFormat:@":%@", exception.name]; fail(@"unsupported_capability"); } }
    return 0;
}
