// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <Inventor/SoDB.h>

#include <src/App/InitApplication.h>

#include <Gui/Selection/SoFCUnifiedSelection.h>

namespace
{

/**
 * A selection or preselection that names a whole object is answered by the
 * root of that object: it writes itself a selection context and reports the
 * change on. Reading a context back is not offered to the outside, so what is
 * checked here is that report - a root that has something to show reports a
 * change, a root of the style that shows nothing stays still, and so does what
 * it holds, since painting the children is the same picture by another way.
 */
class SelectionRootTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        // A root reads the view parameters on its way through an action
        tests::initApplication();
        if (!SoDB::isInitialized()) {
            SoDB::init();
        }
        if (Gui::SoFCSelectionRoot::getClassTypeId().isBad()) {
            Gui::SoFCSeparator::initClass();
            Gui::SoFCSelectionRoot::initClass();
        }
        if (Gui::SoSelectionElementAction::getClassTypeId().isBad()) {
            Gui::SoSelectionElementAction::initClass();
        }
        if (Gui::SoHighlightElementAction::getClassTypeId().isBad()) {
            Gui::SoHighlightElementAction::initClass();
        }
    }

    void SetUp() override
    {
        root = new Gui::SoFCSelectionRoot();
        root->ref();
        held = new Gui::SoFCSelectionRoot();
        root->addChild(held);
    }

    void TearDown() override
    {
        root->unref();
    }

    Gui::SoFCSelectionRoot* root {nullptr};
    Gui::SoFCSelectionRoot* held {nullptr};
};

TEST_F(SelectionRootTest, takesUpTheSelectionOfTheWholeObject)
{
    const auto before = root->getNodeId();

    Gui::SoSelectionElementAction select(Gui::SoSelectionElementAction::All);
    select.apply(root);

    EXPECT_NE(root->getNodeId(), before);
}

TEST_F(SelectionRootTest, takesUpThePreselectionOfTheWholeObject)
{
    const auto before = root->getNodeId();

    Gui::SoHighlightElementAction highlight;
    highlight.setHighlighted(true);
    highlight.apply(root);

    EXPECT_NE(root->getNodeId(), before);
}

TEST_F(SelectionRootTest, showsNothingOfAWholeSelectionWithoutASelectionStyle)
{
    root->selectionStyle = Gui::SoFCSelectionRoot::None;
    const auto rootBefore = root->getNodeId();
    const auto heldBefore = held->getNodeId();

    Gui::SoSelectionElementAction select(Gui::SoSelectionElementAction::All);
    select.apply(root);

    EXPECT_EQ(root->getNodeId(), rootBefore) << "nothing of its own to show";
    EXPECT_EQ(held->getNodeId(), heldBefore) << "and nothing handed down to what it holds";
}

TEST_F(SelectionRootTest, showsNothingOfAWholePreselectionWithoutASelectionStyle)
{
    root->selectionStyle = Gui::SoFCSelectionRoot::None;
    const auto rootBefore = root->getNodeId();
    const auto heldBefore = held->getNodeId();

    Gui::SoHighlightElementAction highlight;
    highlight.setHighlighted(true);
    highlight.apply(root);

    EXPECT_EQ(root->getNodeId(), rootBefore);
    EXPECT_EQ(held->getNodeId(), heldBefore);
}

}  // namespace
