// Read-only native Contacts snapshot. Compile with:
// clang -fobjc-arc -framework Foundation -framework Contacts -framework AddressBook contacts_native.m -o contacts-native
// Grant Contacts access to the stable signed helper separately; never prompts.
#import <Foundation/Foundation.h>
#import <Contacts/Contacts.h>
#import <AddressBook/AddressBook.h>

static id plain(id value) {
    if (!value || value == [NSNull null]) return @"";
    if ([value isKindOfClass:[NSDate class]]) {
        NSISO8601DateFormatter *formatter = [NSISO8601DateFormatter new];
        formatter.formatOptions = NSISO8601DateFormatWithInternetDateTime | NSISO8601DateFormatWithFractionalSeconds;
        return [formatter stringFromDate:[NSDate dateWithTimeIntervalSince1970:floor([value timeIntervalSince1970])]];
    }
    return value;
}
static NSString *stringValue(ABPerson *person, NSString *property) {
    id value = plain([person valueForProperty:property]);
    return [value isKindOfClass:[NSString class]] ? value : @"";
}
static NSArray *multi(ABPerson *person, NSString *property, NSDictionary *keys, NSString *valueKey) {
    ABMultiValue *values = [person valueForProperty:property];
    NSMutableArray *result = [NSMutableArray new];
    for (NSUInteger index = 0; index < values.count; index++) {
        NSMutableDictionary *entry = [@{@"id": plain([values identifierAtIndex:index]),
                                       @"label": plain([values labelAtIndex:index])} mutableCopy];
        id value = [values valueAtIndex:index];
        if (keys) {
            for (NSString *output in keys) entry[output] = plain([value objectForKey:keys[output]]);
        } else entry[valueKey] = plain(value);
        if ([entry[@"label"] isEqual:@""] && [property isEqualToString:kABEmailProperty]) entry[@"label"] = @"Email";
        if ([entry[@"label"] isEqual:@""] && [property isEqualToString:kABPhoneProperty]) entry[@"label"] = @"Phone";
        if ([property isEqualToString:kABSocialProfileProperty]) [entry removeObjectForKey:@"label"];
        if ([property isEqualToString:kABAddressProperty]) {
            entry[@"formattedAddress"] = [[ABAddressBook sharedAddressBook] formattedAddressFromDictionary:value].string ?: @"";
        }
        [result addObject:entry];
    }
    return result;
}
int main(void) {
    @autoreleasepool {
        // Limited authorization isn't a complete snapshot. Do not treat denial
        // as an empty address book and do not invoke requestAccess.
        if ([CNContactStore authorizationStatusForEntityType:CNEntityTypeContacts] != CNAuthorizationStatusAuthorized) return 3;
        ABAddressBook *book = [ABAddressBook sharedAddressBook];
        if (!book) return 4;
        NSMutableArray *contacts = [NSMutableArray new];
        NSDictionary *fields = @{@"firstName": kABFirstNameProperty, @"middleName": kABMiddleNameProperty,
            @"lastName": kABLastNameProperty, @"nickname": kABNicknameProperty, @"maidenName": kABMaidenNameProperty,
            @"organization": kABOrganizationProperty, @"department": kABDepartmentProperty,
            @"jobTitle": kABJobTitleProperty, @"homePage": kABHomePageProperty,
            @"birthDate": kABBirthdayProperty, @"creationDate": kABCreationDateProperty,
            @"modificationDate": kABModificationDateProperty, @"title": kABTitleProperty, @"suffix": kABSuffixProperty};
        for (ABPerson *person in [book people]) {
            NSMutableDictionary *contact = [NSMutableDictionary new];
            contact[@"id"] = person.uniqueId;
            contact[@"note"] = @""; // Filled only after complete read-only replica coverage.
            for (NSString *field in fields) contact[field] = plain([person valueForProperty:fields[field]]);
            CNMutableContact *formatted = [CNMutableContact new];
            formatted.givenName = stringValue(person, kABFirstNameProperty);
            formatted.middleName = stringValue(person, kABMiddleNameProperty);
            formatted.familyName = stringValue(person, kABLastNameProperty);
            formatted.namePrefix = stringValue(person, kABTitleProperty);
            formatted.nameSuffix = stringValue(person, kABSuffixProperty);
            formatted.organizationName = stringValue(person, kABOrganizationProperty);
            contact[@"name"] = [CNContactFormatter stringFromContact:formatted style:CNContactFormatterStyleFullName] ?: @"";
            contact[@"emails"] = multi(person, kABEmailProperty, nil, @"value");
            contact[@"phones"] = multi(person, kABPhoneProperty, nil, @"value");
            contact[@"urls"] = multi(person, kABURLsProperty, nil, @"value");
            contact[@"relatedNames"] = multi(person, kABRelatedNamesProperty, nil, @"value");
            contact[@"addresses"] = multi(person, kABAddressProperty,
                @{@"street": kABAddressStreetKey, @"city": kABAddressCityKey, @"state": kABAddressStateKey,
                  @"zip": kABAddressZIPKey, @"country": kABAddressCountryKey, @"countryCode": kABAddressCountryCodeKey}, nil);
            contact[@"instantMessages"] = multi(person, kABInstantMessageProperty,
                @{@"userName": kABInstantMessageUsernameKey, @"serviceName": kABInstantMessageServiceKey}, nil);
            contact[@"socialProfiles"] = multi(person, kABSocialProfileProperty,
                @{@"url": kABSocialProfileURLKey, @"userName": kABSocialProfileUsernameKey,
                  @"userIdentifier": kABSocialProfileUserIdentifierKey, @"serviceName": kABSocialProfileServiceKey}, nil);
            [contacts addObject:contact];
        }
        NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"success": @YES, @"count": @(contacts.count), @"contacts": contacts} options:0 error:nil];
        if (!data) return 5;
        fwrite(data.bytes, 1, data.length, stdout);
    }
    return 0;
}
