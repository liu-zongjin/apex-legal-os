import Contacts
import Foundation

struct ContactSpec: Decodable {
    let name: String
    let roleType: String
    let phone: String
    let email: String
    let caseTitle: String?
    let caseNumber: String?
}

struct BridgeResult: Encodable {
    let ok: Bool
    let identifier: String?
    let action: String?
    let error: String?
}

/// A contact form may contain several phone numbers in one input field, for
/// example "020-83007496、83007554、83008041".  Contacts.framework represents
/// these as separate `CNLabeledValue`s, so split the human-entered text before
/// saving it rather than creating one unusable combined number.
func splitPhoneNumbers(_ rawValue: String) -> [String] {
    let separators = CharacterSet(charactersIn: ",，、;；\n\r")
    var seen = Set<String>()
    return rawValue
        .components(separatedBy: separators)
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
        .filter { value in
            let identity = value.unicodeScalars
                .filter { CharacterSet.decimalDigits.contains($0) }
                .map(String.init)
                .joined()
            let key = identity.isEmpty ? value : identity
            return seen.insert(key).inserted
        }
}

func phoneIdentity(_ value: String) -> String {
    value.unicodeScalars
        .filter { CharacterSet.decimalDigits.contains($0) }
        .map(String.init)
        .joined()
}

func shortenText(_ text: String, maximumLength: Int) -> String {
    let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard maximumLength > 0, value.count > maximumLength else { return maximumLength > 0 ? value : "" }
    guard maximumLength > 1 else { return "…" }
    return String(value.prefix(maximumLength - 1)) + "…"
}

func shortenCaseTitle(_ title: String, maximumLength: Int) -> String {
    var value = title.trimmingCharacters(in: .whitespacesAndNewlines)
    // 优先去除不影响案件识别的常见冗余表述，再在必要时截短。
    if value.contains("保利墨洲东") && (value.contains("退房") || value.contains("退差")) {
        return "保利退费\(value.contains("系列") ? "系列案" : "")"
    }
    value = value.replacingOccurrences(of: "（仲裁）", with: "")
    value = value.replacingOccurrences(of: "(仲裁)", with: "")
    value = value.replacingOccurrences(of: "系列案件", with: "系列案")
    value = value.replacingOccurrences(of: "纠纷一案", with: "纠纷")
    value = value.replacingOccurrences(of: "退房退差", with: "退费")
    return shortenText(value, maximumLength: maximumLength)
}

func shortenCaseNumber(_ caseNumber: String, maximumLength: Int) -> String {
    let value = caseNumber
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .replacingOccurrences(of: " ", with: "")
        .replacingOccurrences(of: "　", with: "")
    let pattern = "(\\d{4}).*?(?:第)?\\s*(\\d+)\\s*号"
    if let regex = try? NSRegularExpression(pattern: pattern),
       let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
       let yearRange = Range(match.range(at: 1), in: value),
       let serialRange = Range(match.range(at: 2), in: value) {
        return shortenText("\(value[yearRange])-\(value[serialRange])号案", maximumLength: maximumLength)
    }
    guard maximumLength > 0, value.count > maximumLength else { return maximumLength > 0 ? value : "" }
    guard maximumLength > 9 else { return shortenText(value, maximumLength: maximumLength) }
    // 案号较长时同时保留年份/法院等前缀和末尾编号，避免只截取前半段而失去区分度。
    let suffixLength = min(8, maximumLength / 3)
    let prefixLength = maximumLength - suffixLength - 1
    return String(value.prefix(prefixLength)) + "…" + String(value.suffix(suffixLength))
}

func contactDisplayName(_ name: String, caseTitle: String, caseNumber: String) -> String {
    let preservedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
    // 通讯录名称保持紧凑；姓名（包括职务）绝不截短。
    let maximumLength = 52
    guard preservedName.count < maximumLength else { return preservedName }
    let title = caseTitle.trimmingCharacters(in: .whitespacesAndNewlines)
    let number = caseNumber.trimmingCharacters(in: .whitespacesAndNewlines)
    let presentParts = [preservedName, title, number].filter { !$0.isEmpty }
    guard presentParts.count > 1 else { return preservedName }

    let separatorLength = presentParts.count - 1 // "-"
    let availableDetailLength = max(0, maximumLength - preservedName.count - separatorLength)
    var compactTitle = shortenCaseTitle(title, maximumLength: 22)
    var compactNumber = shortenCaseNumber(number, maximumLength: 20)
    if compactTitle.count + compactNumber.count > availableDetailLength {
        if !compactTitle.isEmpty && !compactNumber.isEmpty {
            let numberBudget = min(compactNumber.count, max(1, availableDetailLength / 2))
            let titleBudget = max(0, availableDetailLength - numberBudget)
            compactTitle = shortenCaseTitle(title, maximumLength: titleBudget)
            compactNumber = shortenCaseNumber(number, maximumLength: numberBudget)
        } else if !compactTitle.isEmpty {
            compactTitle = shortenCaseTitle(title, maximumLength: availableDetailLength)
        } else {
            compactNumber = shortenCaseNumber(number, maximumLength: availableDetailLength)
        }
    }
    return [preservedName, compactTitle, compactNumber].filter { !$0.isEmpty }.joined(separator: "-")
}

func emit(_ result: BridgeResult) -> Never {
    let data = try? JSONEncoder().encode(result)
    print(data.flatMap { String(data: $0, encoding: .utf8) } ?? "{\"ok\":false,\"error\":\"无法编码通讯录同步结果\"}")
    exit(result.ok ? 0 : 1)
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    emit(BridgeResult(ok: false, identifier: nil, action: nil, error: "缺少联系人 JSON 文件"))
}

do {
    let data = try Data(contentsOf: URL(fileURLWithPath: args[1]))
    let spec = try JSONDecoder().decode(ContactSpec.self, from: data)
    let store = CNContactStore()
    let semaphore = DispatchSemaphore(value: 0)
    var accessGranted = false
    var accessError: Error?
    store.requestAccess(for: .contacts) { granted, error in
        accessGranted = granted
        accessError = error
        semaphore.signal()
    }
    semaphore.wait()
    guard accessGranted else {
        emit(BridgeResult(ok: false, identifier: nil, action: nil, error: accessError?.localizedDescription ?? "未获得通讯录访问权限，请在系统设置中允许终端或本应用访问通讯录"))
    }

    let containers = try store.containers(matching: nil)
    let defaultIdentifier = store.defaultContainerIdentifier()
    guard let targetContainer = containers.first(where: { $0.identifier == defaultIdentifier })
        ?? containers.first(where: { $0.type == .cardDAV && $0.name.lowercased().contains("icloud") })
        ?? containers.first(where: { $0.type == .cardDAV }) else {
        emit(BridgeResult(ok: false, identifier: nil, action: nil, error: "未找到可写的通讯录账户，请先在通讯录 App 中启用 iCloud 并将其设为默认账户"))
    }

    let keys: [CNKeyDescriptor] = [
        CNContactIdentifierKey as CNKeyDescriptor,
        CNContactGivenNameKey as CNKeyDescriptor,
        CNContactFamilyNameKey as CNKeyDescriptor,
        CNContactOrganizationNameKey as CNKeyDescriptor,
        CNContactPhoneNumbersKey as CNKeyDescriptor,
        CNContactEmailAddressesKey as CNKeyDescriptor,
        CNContactJobTitleKey as CNKeyDescriptor,
        CNContactDepartmentNameKey as CNKeyDescriptor,
        // CNContactNoteKey requires Apple's restricted contacts.notes entitlement.
        // A plain command-line bridge must not fetch or mutate that field.
    ]
    let request = CNContactFetchRequest(keysToFetch: keys)
    request.predicate = CNContact.predicateForContactsInContainer(withIdentifier: targetContainer.identifier)
    let caseTitle = spec.caseTitle?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let caseNumber = spec.caseNumber?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let displayName = contactDisplayName(spec.name, caseTitle: caseTitle, caseNumber: caseNumber)
    let incomingPhoneIdentities = Set(splitPhoneNumbers(spec.phone).map(phoneIdentity).filter { !$0.isEmpty })
    let incomingEmail = spec.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    var matched: CNContact?
    try store.enumerateContacts(with: request) { contact, stop in
        let existingDisplayName = [contact.familyName, contact.givenName].joined()
        let isSameCompositeName = existingDisplayName == displayName || contact.organizationName == displayName
        let isLegacyName = existingDisplayName == spec.name || contact.organizationName == spec.name
        let hasSamePhone = contact.phoneNumbers.contains { incomingPhoneIdentities.contains(phoneIdentity($0.value.stringValue)) }
        let hasSameEmail = !incomingEmail.isEmpty && contact.emailAddresses.contains { String($0.value).lowercased() == incomingEmail }
        let hasSameCaseContext = (!caseTitle.isEmpty && contact.departmentName.contains(caseTitle))
        // 旧版仅以姓名创建的联系人，仅在号码或邮箱一致时迁移为“姓名 - 案件 - 案号”，
        // 以免同名联系人在不同案件中互相覆盖。
        if isSameCompositeName || ((isLegacyName || hasSameCaseContext) && (hasSamePhone || hasSameEmail)) {
            matched = contact
            stop.pointee = true
        }
    }

    let contact = (matched?.mutableCopy() as? CNMutableContact) ?? CNMutableContact()
    contact.familyName = ""
    contact.givenName = displayName
    // Rebuild the list as well as processing the incoming value.  This also
    // fixes contacts that were synced before multi-number splitting existed.
    var updatedPhoneNumbers: [CNLabeledValue<CNPhoneNumber>] = []
    var knownPhoneIdentities = Set<String>()
    func appendPhone(_ phone: String, label: String?) {
        let identity = phoneIdentity(phone)
        let alreadyExists = identity.isEmpty
            ? updatedPhoneNumbers.contains(where: { $0.value.stringValue == phone })
            : knownPhoneIdentities.contains(identity)
        if !alreadyExists {
            updatedPhoneNumbers.append(CNLabeledValue(label: label, value: CNPhoneNumber(stringValue: phone)))
            if !identity.isEmpty { knownPhoneIdentities.insert(identity) }
        }
    }
    for existingPhone in contact.phoneNumbers {
        for phone in splitPhoneNumbers(existingPhone.value.stringValue) {
            appendPhone(phone, label: existingPhone.label)
        }
    }
    for phone in splitPhoneNumbers(spec.phone) {
        appendPhone(phone, label: CNLabelWork)
    }
    contact.phoneNumbers = updatedPhoneNumbers
    if !spec.email.isEmpty && !contact.emailAddresses.contains(where: { String($0.value) == spec.email }) {
        contact.emailAddresses.append(CNLabeledValue(label: CNLabelWork, value: spec.email as NSString))
    }
    if !spec.roleType.isEmpty { contact.jobTitle = spec.roleType }
    if !caseTitle.isEmpty {
        let caseLabel = "关联案件：\(caseTitle)\(caseNumber.isEmpty ? "" : "（案号：\(caseNumber)）")"
        let otherCaseLabels = contact.departmentName
            .split(separator: "；")
            .map(String.init)
            .filter { !$0.contains("关联案件：\(caseTitle)") }
        contact.departmentName = (otherCaseLabels + [caseLabel]).joined(separator: "；")
    }

    let save = CNSaveRequest()
    if matched == nil {
        save.add(contact, toContainerWithIdentifier: targetContainer.identifier)
    } else {
        save.update(contact)
    }
    try store.execute(save)
    emit(BridgeResult(ok: true, identifier: contact.identifier, action: matched == nil ? "created" : "updated", error: nil))
} catch {
    let nsError = error as NSError
    let detail = "\(nsError.localizedDescription) [\(nsError.domain):\(nsError.code)]"
    emit(BridgeResult(ok: false, identifier: nil, action: nil, error: detail))
}
