# Daily Lesson Plan Queue System - Requirements Document

Version: 1.1
Date: November 28, 2024
Author: System Requirements Team

---

## 1. EXECUTIVE SUMMARY

### 1.1 Purpose
The Daily Lesson Plan Queue System provides a structured approach to selecting daily learning topics and activities for early childhood education (ages 2 to 3+ years). The system manages three distinct queues of educational content, ensuring balanced coverage across developmental domains while allowing flexibility in topic selection.

### 1.2 Scope
This system replaces a stratified sampling approach with a simpler FIFO (First-In-First-Out) queue-based system. It supports multiple caregivers working collaboratively to select, skip, and manage learning topics across two primary queues (Knowledge, Skills & Culture; Physical Activities).

### 1.3 Success Criteria
- Caregivers can select daily topics in under 1 minute
- All topics in each queue are covered before any topic repeats
- System is accessible from mobile devices
- Multiple users can interact simultaneously without conflicts
- New topic ideas can be easily added and reviewed

---

## 2. SYSTEM OVERVIEW

### 2.1 Core Concept
The system maintains two independent queues of learning topics:
1. **Knowledge, Skills & Culture Queue** - Academic learning, practical skills, creative pursuits, and cultural activities (combined)
2. **Physical Activities Queue** - Movement, sports, and physical development

Each queue operates as a circular buffer: when all items are completed, the queue automatically refills and begins a new cycle.

### 2.2 Primary Users
- **Primary Caregivers**: Parents or educators who select daily topics
- **Secondary Caregivers**: Additional adults who may select topics on different days
- **System Administrator**: User who manages topic lists and system configuration (may be same as primary caregiver)

---

## 3. FUNCTIONAL REQUIREMENTS

### 3.1 Queue Management

#### 3.1.1 Queue Display
**REQ-QD-001**: The system SHALL display the current (top) item from each queue simultaneously.

**REQ-QD-002**: For each queue item, the system SHALL display:
- Topic/activity name
- Category classification (if applicable)
- Current position in queue (e.g., "1 of 68")
- Source category (original classification from imported data)

**REQ-QD-003**: The system SHALL indicate when a queue is empty.

#### 3.1.2 Item Selection
**REQ-SEL-001**: Users SHALL be able to mark the current item in any queue as "selected" (completed).

**REQ-SEL-002**: When an item is selected, the system SHALL:
- Remove it from the active queue
- Record it in the completion log
- Advance the queue to show the next item

**REQ-SEL-003**: Users SHALL be able to select items from multiple queues independently (selecting from one queue does not affect others).

**REQ-SEL-004**: The system SHALL allow selecting items from both queues in a single session (for daily planning).

#### 3.1.3 Item Skipping
**REQ-SKIP-001**: Users SHALL be able to skip the current item in any queue without marking it as completed.

**REQ-SKIP-002**: When an item is skipped, the system SHALL:
- Move the item to the end of its queue
- Advance the queue to show the next item
- Maintain the item in the active queue for future selection

**REQ-SKIP-003**: Users SHALL be able to skip an item multiple times (each skip moves it to the end again).

#### 3.1.4 Queue Refill and Cycling
**REQ-REFILL-001**: When the last item in a queue is selected, the system SHALL automatically refill the queue with all items from the master list.

**REQ-REFILL-002**: The system SHALL notify users when a queue has been refilled and a new cycle has begun.

**REQ-REFILL-003**: Queue refill SHALL restore items in randomized order.

### 3.2 Development Queue (Needs Rework)

#### 3.2.1 Moving Items to Development
**REQ-DEV-001**: Users SHALL be able to move the current item from any queue to a "Development Queue" for topics that need revision or removal.

**REQ-DEV-002**: When moving an item to the Development Queue, users SHALL be able to provide a reason or note explaining why it needs work.

**REQ-DEV-003**: Items moved to Development Queue SHALL be removed from the active queue and SHALL NOT reappear in future cycles until explicitly restored.

#### 3.2.2 Development Queue Management
**REQ-DEV-004**: The system SHALL maintain a separate Development Queue visible to users.

**REQ-DEV-005**: The Development Queue SHALL display:
- Topic/activity name
- Original queue (Knowledge, Skills & Culture, or Physical)
- Reason for flagging
- Date added to Development Queue

**REQ-DEV-006**: Users SHALL be able to:
- Edit items in the Development Queue
- Delete items from the Development Queue (permanent removal)
- Restore items from Development Queue back to their original active queue
- Move items from Development Queue to a different queue

### 3.3 Ideas Queue (New Topic Suggestions)

#### 3.3.1 Idea Submission
**REQ-IDEA-001**: The system SHALL provide a dedicated interface for submitting new topic ideas for each queue.

**REQ-IDEA-002**: When submitting an idea, users SHALL be able to specify:
- Which queue the idea belongs to (Knowledge, Skills & Culture, or Physical)
- Topic/activity name (required)
- Category or subcategory (optional)
- Description or notes (optional)

**REQ-IDEA-003**: The system SHALL allow quick idea capture with minimal required fields (just topic name and queue selection).

#### 3.3.2 Ideas Queue Management
**REQ-IDEA-004**: When an idea is submitted, the system SHALL:
- Add it directly to the master list for the specified queue
- Add it to the beginning (next up position) of the active queue by default

**REQ-IDEA-005**: Users SHALL be able to view recently added ideas within the system (via an ideas tab or similar interface).

### 3.4 Completion Logging

#### 3.4.1 Completion Records
**REQ-LOG-001**: The system SHALL maintain a log of all completed items (persisted unless manually removed).

**REQ-LOG-002**: Each completion record SHALL include:
- Topic/activity name
- Queue type (Knowledge, Skills & Culture, or Physical)
- Date of selection

**REQ-LOG-003**: Completion records SHALL NOT be automatically deleted.

**REQ-LOG-004**: Users SHALL be able to return individual items from the completed pile back to their active queue without resetting the entire queue.

### 3.5 Master Lists Management

#### 3.5.1 Master List Storage
**REQ-MASTER-001**: The system SHALL maintain master lists for each queue containing all topics.

**REQ-MASTER-002**: Master lists SHALL persist independently of active queues.

**REQ-MASTER-003**: Master lists SHALL be used to refill active queues when cycles complete.

#### 3.5.2 Master List Editing
**REQ-MASTER-004**: Users SHALL be able to view and edit master lists.

**REQ-MASTER-005**: Users SHALL be able to:
- Add new topics to master lists
- Edit existing topics in master lists
- Delete topics from master lists
- Reorder topics in master lists
- Move topics between master lists (change queue assignment)

**REQ-MASTER-006**: Changes to master lists SHALL NOT affect currently active queue items, only future cycles.

**REQ-MASTER-007**: The system SHALL support bulk import of topics to master lists.

**REQ-MASTER-008**: The system SHALL support exporting master lists to common formats (CSV, text, etc.).

### 3.6 Queue Reset and Manual Controls

#### 3.6.1 Manual Queue Reset
**REQ-RESET-001**: Users SHALL be able to manually reset any queue to start a new cycle.

**REQ-RESET-002**: Manual reset SHALL:
- Clear the current active queue
- Refill from the master list
- Increment the cycle counter
- Optionally randomize order

**REQ-RESET-003**: The system SHALL require confirmation before manual reset.

**REQ-RESET-004**: The system SHALL log manual resets with timestamp and user.

#### 3.6.2 Queue Reordering (Lower Priority)
**REQ-REORDER-001**: Users SHALL be able to manually reorder items in active queues.

**REQ-REORDER-002**: Users SHALL be able to move specific items to the front or back of a queue.

---

## 4. NON-FUNCTIONAL REQUIREMENTS

### 4.1 Usability

#### 4.1.1 Mobile Accessibility
**REQ-NFR-001**: The system SHALL be fully functional on mobile devices (smartphones and tablets).

**REQ-NFR-002**: The primary user interface SHALL be optimized for single-handed mobile operation.

**REQ-NFR-003**: All interactive elements SHALL be large enough for easy touch interaction (minimum 44x44 pixels).

#### 4.1.2 Efficiency
**REQ-NFR-004**: Users SHALL be able to select daily topics (all queues) in under 60 seconds.

**REQ-NFR-005**: The system SHALL respond to user actions within 2 seconds under normal conditions.

**REQ-NFR-006**: Queue displays SHALL load within 3 seconds on mobile connections.

#### 4.1.3 Learning Curve
**REQ-NFR-007**: New users SHALL be able to perform basic operations (select, skip) without training.

**REQ-NFR-008**: The system SHALL provide contextual help or tooltips for advanced features.

### 4.2 Reliability

#### 4.2.1 Data Persistence
**REQ-NFR-009**: All data SHALL be persisted immediately upon user actions (no manual save required).

**REQ-NFR-010**: The system SHALL not lose data due to network interruptions or device issues.

**REQ-NFR-011**: The system SHALL support offline operation with synchronization when connection is restored (optional but preferred).

#### 4.2.2 Concurrent Access
**REQ-NFR-012**: The system SHALL support multiple users accessing simultaneously without data corruption.

**REQ-NFR-013**: When concurrent modifications occur, the system SHALL resolve conflicts using last-write-wins or prompt users to reconcile.

**REQ-NFR-014**: Users SHALL see updates made by other users within 5 seconds (for shared/collaborative use).

### 4.3 Performance and Scalability

**REQ-NFR-015**: The system SHALL perform adequately with up to 500 topics per queue.

**REQ-NFR-016**: The system SHALL perform adequately with up to 1000 completion log entries.

**REQ-NFR-017**: The system SHALL support at least 2-3 concurrent users without performance degradation (note: separate user identities are not required).

### 4.4 Accessibility

**REQ-NFR-018**: The system SHALL be usable by caregivers with varying levels of technical expertise.

**REQ-NFR-019**: The system SHALL support multiple languages (optional, nice-to-have).

### 4.5 Cost

**REQ-NFR-021**: The system SHALL use free or low-cost infrastructure (target: $0-10/month).

**REQ-NFR-022**: The system SHALL not require paid software licenses for basic operation.

---

## 5. DATA REQUIREMENTS

### 5.1 Data Entities

#### 5.1.1 Topic/Activity Item
Attributes:
- Unique identifier
- Name/title (required)
- Description (optional)
- Category classification (optional)
- Queue assignment (Knowledge, Skills & Culture, or Physical)
- Date added
- Status (Active, Development, Deleted)

#### 5.1.2 Queue State
Attributes:
- Queue type (Knowledge, Skills & Culture, or Physical)
- Current order of items
- Current position (which item is at the top)

#### 5.1.3 Completion Record
Attributes:
- Unique identifier
- Topic reference
- Queue type
- Completion date
- Notes (optional)

#### 5.1.4 Development Queue Entry
Attributes:
- Unique identifier
- Topic reference
- Original queue
- Reason/issue description
- Date flagged
- Status (Pending Review, In Progress, Resolved)

### 5.2 Data Relationships

**REQ-DATA-001**: Each topic SHALL belong to exactly one queue at a time (Knowledge, Skills & Culture, or Physical).

**REQ-DATA-002**: Each topic MAY have multiple completion records (across cycles).

**REQ-DATA-003**: Each completion record SHALL reference exactly one topic.

**REQ-DATA-004**: Each queue state SHALL reference an ordered list of topics.

**REQ-DATA-005**: Development Queue entries SHALL reference topics that may or may not exist in active queues.

### 5.3 Data Integrity

**REQ-DATA-007**: The system SHALL prevent duplicate topics within the same master list (warn user if attempting to add duplicate).

**REQ-DATA-008**: The system SHALL maintain referential integrity between completion records and topics.

**REQ-DATA-009**: The system SHALL handle deleted topics gracefully in historical records (mark as deleted but preserve records).

**REQ-DATA-010**: The system SHALL validate that queue states contain only valid topic references.

### 5.4 Data Import/Export

**REQ-DATA-011**: The system SHALL support importing initial data from the existing stratified sampling system.

**REQ-DATA-012**: The system SHALL support exporting data in common formats (CSV, JSON, Excel).

**REQ-DATA-013**: The system SHALL support backup and restore operations.

---

## 6. USER INTERFACE REQUIREMENTS

### 6.1 Primary Views

#### 6.1.1 Daily Selection View (Main Dashboard)
**REQ-UI-001**: The Daily Selection View SHALL be the default landing page.

**REQ-UI-002**: The view SHALL display both queue tops simultaneously in a vertical layout.

**REQ-UI-003**: For each queue, the view SHALL show:
- Queue name/icon
- Current topic
- Position indicator
- Action buttons (Select, Skip, Needs Work)

**REQ-UI-004**: Action buttons SHALL be clearly labeled and distinctly colored.

**REQ-UI-005**: The view SHALL display last update timestamp.

**REQ-UI-006**: The view SHALL provide quick access to Ideas submission interface.

#### 6.1.2 Individual Queue View (Optional - for review/reordering)
**REQ-UI-007**: Users MAY be able to view the full list of items in each active queue.

**REQ-UI-008**: The queue view SHALL display items in order with position numbers.

**REQ-UI-009**: The queue view SHALL allow reordering items (drag-and-drop or up/down buttons).

**REQ-UI-010**: The queue view SHALL show queue statistics (total items, progress).

#### 6.1.3 Development Queue View
**REQ-UI-015**: The Development Queue view SHALL display all flagged items grouped or filterable by original queue.

**REQ-UI-016**: For each item, the view SHALL show:
- Topic name
- Original queue
- Reason flagged
- Date flagged
- Status

**REQ-UI-017**: The view SHALL provide actions: Edit, Delete, Restore to Queue.

**REQ-UI-018**: The view SHALL indicate the count of pending development items.

#### 6.1.4 Ideas Submission Interface
**REQ-UI-019**: The system SHALL provide a simple interface for submitting new ideas.

**REQ-UI-020**: The interface SHALL allow specifying:
- Target queue (Knowledge, Skills & Culture, or Physical)
- Topic name
- Optional description

**REQ-UI-021**: The interface SHALL support quick-add functionality with minimal required fields.

#### 6.1.5 Master Lists View
**REQ-UI-024**: The Master Lists view SHALL allow viewing and editing master lists for each queue.

**REQ-UI-025**: The view SHALL support bulk operations (add multiple, delete selected, reorder).

**REQ-UI-026**: The view SHALL show master list statistics (total items, last modified).

### 6.2 User Actions and Interactions
Note: Focus on functionality first; visual polish is secondary (implement if easy).

#### 6.2.1 Action Buttons
**REQ-UI-027**: Action buttons SHALL provide clear visual feedback when pressed (state change, animation).

**REQ-UI-028**: Destructive actions (delete, reset) SHALL require confirmation.

**REQ-UI-029**: The system SHALL provide undo functionality for recent actions where feasible.

#### 6.2.2 Forms and Input
**REQ-UI-030**: Forms SHALL use appropriate input types (text, textarea, dropdowns, date pickers).

**REQ-UI-031**: Required fields SHALL be clearly marked.

**REQ-UI-032**: Forms SHALL provide inline validation with helpful error messages.

**REQ-UI-033**: Forms SHALL support keyboard navigation and submission.

#### 6.2.3 Navigation
**REQ-UI-034**: The system SHALL provide consistent navigation across all views (menu, tabs, or sidebar).

**REQ-UI-035**: Users SHALL be able to return to the Daily Selection View from any other view with one action.

**REQ-UI-036**: The system SHALL indicate the current view/page.

### 6.3 Notifications and Feedback

**REQ-UI-037**: The system SHALL provide immediate visual feedback for user actions (success messages, error alerts).

**REQ-UI-038**: The system SHALL notify users when a queue has been refilled.

**REQ-UI-039**: The system SHALL notify users when new ideas have been submitted (if multi-user).

**REQ-UI-040**: Notifications SHALL be non-intrusive and dismissible.

---

## 7. USER SCENARIOS AND USE CASES

### 7.1 Daily Planning Scenario

**Actor**: Primary Caregiver  
**Goal**: Select today's learning topics across both domains

**Main Success Scenario**:
1. User opens the system (bookmarked or app icon)
2. System displays Daily Selection View with current top items from both queues
3. User reviews the Knowledge, Skills & Culture topic
4. User clicks "Select This" button
5. System marks topic as completed, shows confirmation, advances queue
6. User reviews Physical Activity topic
7. User decides this topic doesn't fit today's schedule
8. User clicks "Skip to Back" button
9. System moves topic to end of queue, shows next topic
10. User reviews new Physical Activity topic and selects it
11. User now has two selected topics for the day and can close the system

**Alternate Scenarios**:
- 4a. User doesn't like the topic and flags it with "Needs Work"
  - 4a1. System prompts for reason
  - 4a2. User enters "Too advanced for current age"
  - 4a3. System moves to Development Queue, shows next topic from same queue
- 10a. User skips multiple topics before finding a good one
  - System allows unlimited skips, each moving items to end of queue

**Frequency**: Daily  
**Priority**: Critical

### 7.2 Adding New Topic Ideas

**Actor**: Secondary Caregiver
**Goal**: Capture inspiration for new learning topics while out

**Main Success Scenario**:
1. User observes child showing interest in construction vehicles at a park
2. User opens system on mobile device
3. User navigates to Ideas submission interface
4. User selects "Knowledge, Skills & Culture" as target queue
5. User enters topic: "Construction vehicles and equipment"
6. User optionally adds note: "Child fascinated by bulldozer at park"
7. User submits idea
8. System adds topic directly to Knowledge, Skills & Culture master list
9. System adds topic to beginning of Knowledge, Skills & Culture active queue (next up)
10. System confirms submission
11. User closes system

**Alternate Scenarios**:
- 4a. User uses quick-add widget/shortcut
  - 4a1. Widget shows minimal form (just topic name and queue dropdown)
  - 4a2. Faster capture for on-the-go ideas

**Frequency**: Weekly
**Priority**: High

### 7.3 Managing Development Queue

**Actor**: Primary Caregiver  
**Goal**: Review and fix flagged topics that need rework

**Main Success Scenario**:
1. User has accumulated 10 items in Development Queue
2. User navigates to Development Queue view
3. User sees topics grouped by original queue
4. User reviews first item: "Theater and drama" (reason: "Too abstract for toddlers")
5. User decides to modify the topic
6. User edits to "Puppet play and pretend theater"
7. User restores to Knowledge, Skills & Culture queue
8. System adds modified topic back to Knowledge, Skills & Culture queue at end
9. User reviews second item: "Advanced calculus" (added by mistake)
10. User deletes item permanently
11. User continues reviewing remaining items

**Frequency**: Monthly
**Priority**: Medium

### 7.4 Reviewing Learning History

**Actor**: Primary Caregiver  
**Goal**: Reflect on learning activities over the past month

**Main Success Scenario**:
1. User navigates to Completion History view
2. User sets date filter to last 30 days
3. System displays 45 completed items chronologically
4. User reviews topics by queue:
   - Knowledge, Skills & Culture: 32 items
   - Physical: 13 items
5. User notices good balance across domains
6. User sees some topics were completed in both Cycle 1 and Cycle 2
7. User notes patterns (certain categories more frequently selected)
8. User uses insights to plan future topic additions

**Frequency**: Monthly
**Priority**: Low

### 7.5 Cycle Completion

**Actor**: System (automated), User (notified)  
**Goal**: Complete a queue cycle and start fresh

**Main Success Scenario**:
1. User selects the last item in Knowledge, Skills & Culture queue (item 316 of 316)
2. System marks item as completed
3. System detects queue is now empty
4. System automatically refills queue from master list (randomized order)
5. System displays notification: "Knowledge, Skills & Culture queue complete! Starting new cycle."
6. System shows first topic from new cycle
7. User acknowledges and continues

**Frequency**: Varies by queue (Knowledge, Skills & Culture: ~10-12 months, Physical: ~4 months)
**Priority**: High

---

## 8. TECHNICAL CONSIDERATIONS (Platform-Agnostic)

### 8.1 Data Storage
- System requires persistent storage for topics, queue states, completion logs, and metadata
- Estimated storage: 100-500 KB for all data
- Data should be easily exportable and importable

### 8.2 Authentication and Authorization
- System is designed for single household use
- No authentication required (or minimal authentication if hosted publicly)
- No separate user identities needed - all users have full access
- Multiple people can use the system, but no need to track who made each action

### 8.3 Synchronization
- Multi-device access requires synchronization mechanism
- Changes should propagate to all devices within seconds
- Conflict resolution: Last-write-wins or merge strategies

### 8.4 Offline Support (Nice-to-Have)
- System should cache current queue states for offline viewing
- System should queue actions taken offline for synchronization when online
- System should alert user when operating offline

### 8.5 Backup and Recovery
- System should support manual or automatic backups
- Backups should include all queues, master lists, completion history, and configuration
- System should support restoration from backup

---

## 9. CONSTRAINTS AND ASSUMPTIONS

### 9.1 Constraints
- CONSTRAINT-001: System must be accessible from mobile devices (primary constraint)
- CONSTRAINT-002: System should have minimal to no monthly cost
- CONSTRAINT-003: System should not require specialized software installation
- CONSTRAINT-004: System must support at least 2-3 concurrent users
- CONSTRAINT-005: Implementation should be achievable within reasonable timeframe (days, not weeks)

### 9.2 Assumptions
- ASSUMPTION-001: Users have reliable internet access (at least intermittently)
- ASSUMPTION-002: Users have smartphones or tablets with modern browsers
- ASSUMPTION-003: Initial data import will come from existing Python script (433 items)
- ASSUMPTION-004: Average daily usage is selecting 1-3 items (one per queue)
- ASSUMPTION-005: Topics will be managed in English (primary language)
- ASSUMPTION-006: Users have basic technical literacy (can use apps, websites)

---

## 10. FUTURE ENHANCEMENTS (Out of Scope for v1)

### 10.1 Potential Features for v2+
- **Lesson plan generation**: Automatically generate detailed lesson plans from selected topics
- **Scheduling**: Schedule topics for specific future dates
- **Reminders**: Notify users of daily topic selection
- **Custom categories**: User-defined categories and subcategories
- **Tags and metadata**: Tag topics with themes, skills, materials needed
- **Search and filter**: Advanced search across all topics
- **Randomization options**: Shuffle queue order periodically
- **Collaboration features**: Comments, notes, ratings on topics
- **Resource linking**: Attach videos, documents, or links to topics
- **Progress tracking**: Track child's development and skill mastery
- **Multiple children**: Support for tracking multiple children separately
- **Reporting**: Generate reports on learning activities
- **Integration**: Connect with external lesson plan resources or curricula
- **Mobile app**: Native iOS/Android app (vs. web-based)

### 10.2 Advanced Analytics
- Topic popularity (most selected vs. most skipped)
- Time-based patterns (seasonal topics, day-of-week patterns)
- User activity metrics
- Cycle completion forecasting

---

## 11. ACCEPTANCE CRITERIA

### 11.1 Minimum Viable Product (MVP)
The system SHALL be considered complete for v1 when:
- ✅ Both queues are functional (Knowledge, Skills & Culture; Physical)
- ✅ Users can select, skip, and flag topics
- ✅ Completion log records all selections
- ✅ Development queue stores flagged topics with reasons
- ✅ New ideas can be submitted and are added directly to queues
- ✅ Queues automatically refill (randomized) when cycles complete
- ✅ System is accessible via mobile device
- ✅ Multiple users can access simultaneously without conflicts
- ✅ Initial data (433 items) successfully imported
- ✅ Daily topic selection takes under 60 seconds
- ✅ System costs under $10/month to operate

### 11.2 User Acceptance
The system SHALL be considered successful when:
- Users prefer it over the previous stratified sampling system
- Users report it saves time compared to manual planning
- Users use it consistently for at least 2 weeks
- At least 80% of queued topics are being utilized (not skipped excessively)
- New ideas are being added regularly (at least weekly)
- Users would recommend the system to other educators

---

## 12. GLOSSARY

**Active Queue**: The current working queue of topics for each domain, from which users select daily topics.

**Cycle**: One complete iteration through all topics in a queue. When all topics are selected, a new cycle begins.

**Development Queue**: A holding area for topics that need revision, editing, or removal. Topics here are not part of active queues.

**Master List**: The authoritative collection of all topics for each queue. Used to refill active queues when cycles complete.

**Queue**: An ordered list of topics or activities. The system has two main queues (Knowledge, Skills & Culture; Physical) plus the Development Queue.

**Select**: Mark a topic as completed for the day. Removes it from the active queue and logs it in completion history.

**Skip**: Move a topic to the end of the queue without marking it as completed. The topic remains in the active queue.

**Topic**: A single learning subject or activity. The atomic unit of the system.

---

## 13. REVISION HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2024-11-26 | System Requirements Team | Initial requirements document |
| 1.1 | 2024-11-28 | System Requirements Team | Updated based on inline comments: Simplified ideas workflow (direct to queues), removed cycle tracking, simplified logging (date only, no timestamps), removed user tracking, streamlined UI requirements, clarified single-user focus |

---

## 14. APPENDICES

### Appendix A: Initial Data Summary
- Knowledge, Skills & Culture Queue: 316 items (combined from former Arts & Culture and Knowledge & Skills queues)
- Physical Activities Queue: 117 items
- Total: 433 items

### Appendix B: Original Source Categories
The 433 items are mapped from the following original categories in the stratified sampling system:
- Knowledge & Culture Categories: 35 combined categories (19 knowledge categories like "Cross-Domain Foundational Concepts", "Physical World - Life Sciences", etc. + 16 activity categories like "Creative and Expressive - Visual Arts", "Social and Cultural - Interpersonal", etc.)
- Physical Activity Categories: 10 categories (e.g., "Individual Sports", "Team Sports", "Mind-Body Activities", etc.)

These source categories are preserved as metadata on each topic for future reference and organization.

---

END OF REQUIREMENTS DOCUMENT
