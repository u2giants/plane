-- Populate list_space_map from snapshot
-- Run this SQL against D1 to enable division-level analysis

DELETE FROM list_space_map;

INSERT INTO list_space_map
  (list_id, list_name, space_id, space_name, folder_id, folder_name)
VALUES
('13194624', 'Licensing Management', '4294720', 'POP Creations', '8445305', 'Design Management'),
('15061776', 'Edge Generic', '2571984', 'Spruce Line', '8484698', 'Edge Home Folder'),
('15061838', 'Dev', '2571984', 'Spruce Line', '8484698', 'Edge Home Folder'),
('192287164', 'Store Shopping', '2571984', 'Spruce Line', '90117037827', 'hidden'),
('900500326811', 'Freelancers Licensed', '4294720', 'POP Creations', '8445305', 'Design Management'),
('900500417603', 'Carlos', '4294720', 'POP Creations', '90050237824', 'Other Projects'),
('901103451188', 'New Prod Development', '4294720', 'POP Creations', '8445305', 'Design Management'),
('901103451229', 'Customer Refresh', '4294720', 'POP Creations', '8445305', 'Design Management'),
('901103451267', 'Customer Category Expansion', '4294720', 'POP Creations', '8445305', 'Design Management'),
('901103489845', 'New Prod Ideas', '2571984', 'Spruce Line', '90111858337', 'hidden'),
('901103514425', 'Licensor''s projects', '4294720', 'POP Creations', '8445305', 'Design Management'),
('901103525796', 'Licensing Administration Tasks', '4294720', 'POP Creations', '90111880487', 'Licensed Team Admin Task'),
('901104136630', 'Newsletter Whiteboard', NULL, NULL, NULL, NULL),
('901104141567', 'Sourcing/Sampling Projects', '4294720', 'POP Creations', '8445305', 'Design Management'),
('901107307251', 'Freelancers Generic', '2571984', 'Spruce Line', '90117589456', 'hidden'),
('901109204835', 'General Presentations', '2571984', 'Spruce Line', '8484698', 'Edge Home Folder'),
('901110768081', 'PAPERGOODS', NULL, NULL, NULL, NULL),
('901111970161', 'Technical Leadership', NULL, NULL, NULL, NULL),
('901111985957', 'Carlos', NULL, NULL, NULL, NULL),
('901113079677', 'Nathalie - Tasks', '2571984', 'Spruce Line', '8484698', 'Edge Home Folder'),
('901113451000', 'development', '90114122073', 'designflow', '90117810115', 'Development');