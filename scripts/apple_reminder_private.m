// ReminderKit API declarations and save pattern adapted from RemCTL (MIT).
// Source: viticci/remctl d3985293a01aa1c2da761ff442812a148be9964f.
// See third_party/remctl/LICENSE. No direct database reads or writes.
#import "apple_pim_attachment.h"

@interface REMObjectID : NSObject
+ (id)objectIDWithURL:(NSURL *)url;
- (NSUUID *)uuid;
@end
@interface REMStore : NSObject
- (id)fetchReminderWithObjectID:(id)objectID error:(NSError **)error;
@end
@interface REMSaveRequest : NSObject
- (instancetype)initWithStore:(REMStore *)store;
- (id)updateReminder:(id)reminder;
- (id)addReminderWithTitle:(NSString *)title toReminderSubtaskContextChangeItem:(id)context;
- (BOOL)saveSynchronouslyWithError:(NSError **)error;
@end
@interface NSObject (PersonalContextReminderKit)
- (id)remObjectID;
- (id)parentReminder;
- (id)subtaskContext;
- (id)urgentAlarmContext;
- (id)flaggedContext;
- (id)hashtagContext;
- (id)attachmentContext;
- (NSArray *)hashtags;
- (NSString *)name;
- (void)removeAllHashtags;
- (id)addHashtagWithType:(NSInteger)type name:(NSString *)name;
- (NSArray *)attachments;
- (NSArray *)fileAttachments;
- (NSURL *)fileURL;
- (NSString *)uti;
- (void)removeAttachment:(id)attachment;
- (id)addImageAttachmentWithData:(NSData *)data uti:(NSString *)uti width:(NSUInteger)width height:(NSUInteger)height;
- (NSArray *)fetchRemindersWithError:(NSError **)error;
- (BOOL)isUrgentStateEnabledForCurrentUser;
- (void)setIsUrgentStateEnabledForCurrentUser:(BOOL)value;
- (NSInteger)flagged;
- (void)setFlagged:(NSInteger)value;
- (NSString *)titleAsString;
- (NSString *)notesAsString;
- (void)setNotesAsString:(NSString *)value;
@end

static BOOL started = NO;
static NSString *stage = @"input";
static void output(NSDictionary *value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingSortedKeys error:nil];
    if (data) puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
}
static void fail(NSString *code) {
    output(@{@"success": @NO, @"write_started": @(started), @"error_code": code, @"stage": stage});
    exit(0);
}
static NSString *identifier(id reminder) {
    if (!reminder || ![reminder respondsToSelector:@selector(remObjectID)]) return @"";
    return [[[reminder remObjectID] uuid] UUIDString] ?: @"";
}
static id fetch(REMStore *store, NSString *identifier) {
    if (![identifier isKindOfClass:NSString.class] || ![[NSUUID alloc] initWithUUIDString:identifier]) fail(@"invalid_fields");
    NSURL *url = [NSURL URLWithString:[@"x-apple-reminderkit://REMCDReminder/" stringByAppendingString:identifier]];
    NSError *error = nil;
    id reminder = [store fetchReminderWithObjectID:[REMObjectID objectIDWithURL:url] error:&error];
    if (!reminder) fail(@"item_not_found");
    return reminder;
}
static NSDictionary *inspect(id reminder) {
    stage = @"read_selectors";
    for (NSString *name in @[@"subtaskContext", @"urgentAlarmContext", @"parentReminder"]) {
        if (![reminder respondsToSelector:NSSelectorFromString(name)]) fail(@"unsupported_capability");
    }
    id context = [reminder subtaskContext];
    id urgent = [reminder urgentAlarmContext];
    stage = @"read_contexts";
    if ((context && ![context respondsToSelector:@selector(fetchRemindersWithError:)]) ||
        (urgent && ![urgent respondsToSelector:@selector(isUrgentStateEnabledForCurrentUser)])) fail(@"unsupported_capability");
    NSError *error = nil;
    stage = @"read_subtasks";
    NSArray *children = context ? [context fetchRemindersWithError:&error] : @[];
    if (error || ![children isKindOfClass:NSArray.class]) fail(@"receiver_unavailable");
    NSMutableArray *subtasks = [NSMutableArray array];
    for (id child in children) {
        [subtasks addObject:@{@"item_id": identifier(child), @"title": [child titleAsString] ?: @"",
                             @"notes": [child notesAsString] ?: @""}];
    }
    [subtasks sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        return [a[@"item_id"] compare:b[@"item_id"]];
    }];
    stage = @"read_urgent_parent";
    id tags = [reminder respondsToSelector:@selector(hashtagContext)] ? [reminder hashtagContext] : nil;
    NSMutableArray *names = [NSMutableArray array];
    if (tags && [tags respondsToSelector:@selector(hashtags)]) for (NSObject *tag in [tags hashtags]) [names addObject:[tag name]];
    [names sortUsingSelector:@selector(compare:)];
    id files = [reminder respondsToSelector:@selector(attachmentContext)] ? [reminder attachmentContext] : nil;
    NSMutableArray *attachments = [NSMutableArray array];
    if (files && [files respondsToSelector:@selector(fileAttachments)]) for (id file in [files fileAttachments]) {
        NSData *bytes = [file respondsToSelector:@selector(fileURL)] ? PCLocalBytes([file fileURL]) : nil;
        [attachments addObject:@{@"attachment_id":identifier(file), @"uti":[file uti] ?: @"",
            @"available":@(bytes != nil), @"sha256":bytes ? PCSHA(bytes) : @"", @"bytes":@(bytes.length)}];
    }
    [attachments sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"attachment_id"] compare:b[@"attachment_id"]]; }];
    return @{@"urgent": @([urgent isUrgentStateEnabledForCurrentUser]),
             @"supports_urgent": @(urgent != nil), @"supports_subtasks": @(context != nil),
             @"supports_tags":@(tags != nil), @"tags":names, @"attachments":attachments,
             @"supports_image_attachments":@(files != nil), @"supports_pdf_attachments":@NO,
             @"parent_id": identifier([reminder parentReminder]), @"subtasks": subtasks};
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        @try {
            if (argc != 2) fail(@"invalid_fields");
            NSData *input = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
            if (!input || input.length > 8388608) fail(@"invalid_fields");
            NSDictionary *request = [NSJSONSerialization JSONObjectWithData:input options:0 error:nil];
            if (![request isKindOfClass:NSDictionary.class]) fail(@"invalid_fields");
            NSString *operation = request[@"operation"];
            REMStore *store = [REMStore new];
            stage = @"fetch";
            id reminder = fetch(store, request[@"item_id"]);
            NSDictionary *before = inspect(reminder);
            if ([operation isEqualToString:@"inspect"]) {
                output(@{@"success": @YES, @"metadata": before});
                return 0;
            }
            if (![operation isEqualToString:@"update_private"]) fail(@"invalid_fields");
            NSDictionary *changes = request[@"changes"];
            if (![changes isKindOfClass:NSDictionary.class] || changes.count == 0) fail(@"invalid_fields");
            NSSet *allowed = [NSSet setWithArray:@[@"urgent", @"add_subtasks", @"set_tags", @"add_tags", @"remove_tags", @"add_attachments", @"remove_attachments"]];
            if (![[NSSet setWithArray:changes.allKeys] isSubsetOfSet:allowed]) fail(@"unsupported_capability");
            REMSaveRequest *save = [[REMSaveRequest alloc] initWithStore:store];
            stage = @"update_request";
            id change = [save updateReminder:reminder];
            if (!change) fail(@"unsupported_capability");
            NSMutableArray *expectedTags = [before[@"tags"] mutableCopy];
            if (changes[@"set_tags"] || changes[@"add_tags"] || changes[@"remove_tags"]) {
                stage = @"set_tags";
                id context = [change hashtagContext];
                if (!context || ![context respondsToSelector:@selector(removeAllHashtags)] ||
                    ![context respondsToSelector:@selector(addHashtagWithType:name:)]) fail(@"unsupported_capability");
                if (changes[@"set_tags"]) expectedTags = [changes[@"set_tags"] mutableCopy];
                else {
                    for (NSString *tag in changes[@"remove_tags"]) {
                        NSIndexSet *matches = [expectedTags indexesOfObjectsPassingTest:^BOOL(NSString *name, NSUInteger index, BOOL *stop) { return [name caseInsensitiveCompare:tag] == NSOrderedSame; }];
                        [expectedTags removeObjectsAtIndexes:matches];
                    }
                    for (NSString *tag in changes[@"add_tags"]) {
                        BOOL exists = NO;
                        for (NSString *name in expectedTags) if ([name caseInsensitiveCompare:tag] == NSOrderedSame) exists = YES;
                        if (!exists) [expectedTags addObject:tag];
                    }
                }
                [context removeAllHashtags];
                for (NSString *name in expectedTags) if (![context addHashtagWithType:1 name:name]) fail(@"native_error");
            }
            NSMutableSet *expectedAttachmentIDs = [NSMutableSet setWithArray:[before[@"attachments"] valueForKey:@"attachment_id"]];
            NSMutableArray *addedHashes = [NSMutableArray array];
            if (changes[@"add_attachments"] || changes[@"remove_attachments"]) {
                stage = @"attachments";
                id context = [change attachmentContext];
                if (!context || ![context respondsToSelector:@selector(attachments)]) fail(@"unsupported_capability");
                for (NSString *target in changes[@"remove_attachments"]) {
                    id match = nil;
                    for (id file in [context attachments]) if ([identifier(file) isEqual:target]) match = file;
                    if (!match || ![expectedAttachmentIDs containsObject:target] || ![context respondsToSelector:@selector(removeAttachment:)]) fail(@"invalid_fields");
                    [context removeAttachment:match];
                    [expectedAttachmentIDs removeObject:target];
                }
                for (NSDictionary *spec in changes[@"add_attachments"]) {
                    if (![context respondsToSelector:@selector(addImageAttachmentWithData:uti:width:height:)]) fail(@"unsupported_capability");
                    NSUInteger width = 0, height = 0;
                    NSData *bytes = PCFileData(spec, NO, &width, &height);
                    if (!bytes) fail(@"invalid_fields");
                    if ([[before[@"attachments"] valueForKey:@"sha256"] containsObject:spec[@"sha256"]]) fail(@"invalid_fields");
                    id file = [context addImageAttachmentWithData:bytes uti:[spec[@"media_type"] isEqual:@"image/png"] ? @"public.png" : @"public.jpeg" width:width height:height];
                    if (!file || identifier(file).length == 0) fail(@"native_error");
                    [expectedAttachmentIDs addObject:identifier(file)];
                    [addedHashes addObject:spec[@"sha256"]];
                }
            }
            if (changes[@"urgent"]) {
                stage = @"set_urgent";
                if (CFGetTypeID((__bridge CFTypeRef)changes[@"urgent"]) != CFBooleanGetTypeID()) fail(@"invalid_fields");
                id urgent = [change urgentAlarmContext];
                if (!urgent) { stage = @"urgent_context_missing"; fail(@"unsupported_capability"); }
                if (![urgent respondsToSelector:@selector(setIsUrgentStateEnabledForCurrentUser:)]) { stage = @"urgent_setter_missing"; fail(@"unsupported_capability"); }
                [urgent setIsUrgentStateEnabledForCurrentUser:[changes[@"urgent"] boolValue]];
            }
            NSArray *specs = changes[@"add_subtasks"];
            NSMutableArray *created = [NSMutableArray array];
            if (specs) {
                stage = @"add_subtasks";
                if (![specs isKindOfClass:NSArray.class] || specs.count == 0 || specs.count > 50) fail(@"invalid_fields");
                id context = [change subtaskContext];
                if (!context) { stage = @"subtask_context_missing"; fail(@"unsupported_capability"); }
                if (![save respondsToSelector:@selector(addReminderWithTitle:toReminderSubtaskContextChangeItem:)]) { stage = @"subtask_creator_missing"; fail(@"unsupported_capability"); }
                for (NSDictionary *spec in specs) {
                    if (![spec isKindOfClass:NSDictionary.class]) fail(@"invalid_fields");
                    NSString *title = spec[@"title"];
                    if (![title isKindOfClass:NSString.class] || title.length == 0 || title.length > 500) fail(@"invalid_fields");
                    id child = [save addReminderWithTitle:title toReminderSubtaskContextChangeItem:context];
                    if (!child) fail(@"unsupported_capability");
                    if (spec[@"notes"]) {
                        stage = @"subtask_notes";
                        if (![spec[@"notes"] isKindOfClass:NSString.class] || [spec[@"notes"] length] > 20000) fail(@"invalid_fields");
                        if (![child respondsToSelector:@selector(setNotesAsString:)]) fail(@"unsupported_capability");
                        [child setNotesAsString:spec[@"notes"]];
                    }
                    [created addObject:@{@"item_id": identifier(child), @"title": title, @"notes": spec[@"notes"] ?: @""}];
                }
            }
            started = YES;
            stage = @"save";
            NSError *error = nil;
            if (![save saveSynchronouslyWithError:&error]) fail(@"native_error");
            REMStore *fresh = [REMStore new];
            NSDictionary *after = inspect(fetch(fresh, request[@"item_id"]));
            if (![[NSSet setWithArray:after[@"tags"]] isEqual:[NSSet setWithArray:expectedTags]]) fail(@"verification_failed");
            if (![[NSSet setWithArray:[after[@"attachments"] valueForKey:@"attachment_id"]] isEqual:expectedAttachmentIDs]) fail(@"verification_failed");
            for (NSString *hash in addedHashes) if (![[after[@"attachments"] valueForKey:@"sha256"] containsObject:hash]) fail(@"verification_failed");
            if (changes[@"urgent"] && ![changes[@"urgent"] isEqual:after[@"urgent"]]) fail(@"verification_failed");
            for (NSDictionary *child in created) {
                if (![after[@"subtasks"] containsObject:child]) fail(@"verification_failed");
            }
            for (NSDictionary *child in before[@"subtasks"]) {
                if (![after[@"subtasks"] containsObject:child]) fail(@"verification_failed");
            }
            output(@{@"success": @YES, @"verified": @YES, @"item_id": request[@"item_id"], @"metadata": after});
        } @catch (NSException *exception) {
            stage = [stage stringByAppendingFormat:@":%@", exception.name];
            fail(@"unsupported_capability");
        }
    }
    return 0;
}
